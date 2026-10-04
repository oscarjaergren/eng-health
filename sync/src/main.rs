use std::process::ExitCode;

use prsync::config::Settings;
use prsync::store::Store;

// The sync command arrives with the GitHub source; for now this checks the
// configuration and opens (or creates) the database.
fn main() -> ExitCode {
    dotenvy::dotenv().ok();
    let settings = match Settings::from_process_env() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Configuration problem: {e}");
            return ExitCode::from(2);
        }
    };
    match Store::open(&settings.db_path()).and_then(|s| s.version()) {
        Ok(v) => {
            println!("{} ok (revision {v})", settings.db_path().display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("{e}");
            ExitCode::FAILURE
        }
    }
}
