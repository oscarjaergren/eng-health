use std::path::Path;
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use clap::{Parser, Subcommand, ValueEnum};
use prsync::config::Settings;
use prsync::model::Platform;
use prsync::source::azure::Azure;
use prsync::source::github::GitHub;
use prsync::store::Store;
use prsync::sync::{Event, Options, Report, sync_platform};
use tracing_subscriber::EnvFilter;

/// Sync pull requests from Azure DevOps and GitHub into the PR analytics database.
///
/// Reads the same `.env` settings as the dashboard.
#[derive(Parser)]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Fetch new and changed pull requests.
    Sync {
        /// Re-read every pull request, not just recent ones.
        #[arg(long)]
        full: bool,
        /// Delete the local data first (implies --full).
        #[arg(long)]
        reset: bool,
        /// How to report progress on stdout.
        #[arg(long, value_enum, default_value_t = ProgressFormat::None)]
        progress: ProgressFormat,
    },
    /// Show when each platform last synced.
    Status,
}

#[derive(Clone, Copy, PartialEq, Eq, ValueEnum)]
enum ProgressFormat {
    None,
    /// One JSON object per line, for the dashboard.
    Json,
}

const EXIT_ERRORS: u8 = 1;
const EXIT_CONFIG: u8 = 2;
const EXIT_INTERRUPTED: u8 = 130;

#[tokio::main]
async fn main() -> ExitCode {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .with_writer(std::io::stderr)
        .init();

    let cli = Cli::parse();
    let settings = match Settings::from_process_env() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Configuration problem: {e}");
            return ExitCode::from(EXIT_CONFIG);
        }
    };
    let store = match Store::open(&settings.db_path()) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(EXIT_ERRORS);
        }
    };

    match cli.command {
        Command::Status => status(&store, &settings.db_path()),
        Command::Sync {
            full,
            reset,
            progress,
        } => sync(settings, store, full || reset, reset, progress).await,
    }
}

fn status(store: &Store, path: &Path) -> ExitCode {
    println!("{}", path.display());
    for platform in [Platform::AzureDevops, Platform::Github] {
        match store.sync_state(platform) {
            Ok(s) => {
                let when = s
                    .last_sync
                    .map_or_else(|| "never".to_owned(), |t| t.to_rfc3339());
                let error = s
                    .last_error
                    .map(|e| format!(" (last attempt failed: {e})"))
                    .unwrap_or_default();
                println!("  {platform}: last synced {when}{error}");
            }
            Err(e) => {
                eprintln!("{e}");
                return ExitCode::from(EXIT_ERRORS);
            }
        }
    }
    ExitCode::SUCCESS
}

async fn sync(
    settings: Settings,
    mut store: Store,
    full: bool,
    reset: bool,
    progress: ProgressFormat,
) -> ExitCode {
    if settings.azure.is_none() && settings.github.is_none() {
        eprintln!("No platform configured. Copy .env.example to .env and fill it in.");
        return ExitCode::from(EXIT_CONFIG);
    }
    if reset && let Err(e) = store.clear() {
        eprintln!("{e}");
        return ExitCode::from(EXIT_ERRORS);
    }

    let stop = Arc::new(AtomicBool::new(false));
    let flag = Arc::clone(&stop);
    tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            tracing::warn!("stopping after the current batch");
            flag.store(true, Ordering::Relaxed);
        }
    });

    let emit = move |event: Event| {
        if progress == ProgressFormat::Json {
            println!(
                "{}",
                serde_json::to_string(&event).expect("events serialise")
            );
        }
    };
    let opts = Options {
        full,
        workers: settings.max_workers,
        stop: Arc::clone(&stop),
        on_event: &emit,
    };
    let store = Arc::new(Mutex::new(store));
    let mut results = Vec::new();
    if let Some(az) = &settings.azure {
        results.push(sync_platform(&Azure::new(az), &store, &opts).await);
    }
    if let Some(gh) = &settings.github {
        results.push(sync_platform(&GitHub::new(gh.clone()), &store, &opts).await);
    }
    let reports: Vec<Report> = match results.into_iter().collect() {
        Ok(reports) => reports,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(EXIT_ERRORS);
        }
    };

    for r in &reports {
        emit(Event::Report(r.clone()));
        for e in &r.errors {
            eprintln!("{}: {e}", r.platform);
        }
    }
    if stop.load(Ordering::Relaxed) {
        ExitCode::from(EXIT_INTERRUPTED)
    } else if reports.iter().all(Report::ok) {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(EXIT_ERRORS)
    }
}
