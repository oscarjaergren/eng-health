//! Syncs pull requests and GitHub Actions runs into the SQLite database that the Python
//! dashboard reads.
//!
//! The modules are private and everything `main.rs` and the integration tests need is
//! re-exported below. That list is the crate's surface: rustc reports any other item that
//! nothing uses as dead code, which it never does for an item a public module exports.

mod config;
mod http;
mod model;
mod pipelines;
mod rules;
mod source;
mod store;
mod sync;

pub use config::{AzureSettings, GitHubSettings, OwnerType, Settings};
pub use model::{Platform, PullRequest, Repo, State, Timestamp};
pub use pipelines::{
    Job, MODULE_KEY as PIPELINES_KEY, failed_tests, failures_in, sync as sync_pipelines,
};
pub use rules::parse_time;
pub use source::{People, Source, SourceError};
pub use store::{SCHEMA_VERSION, Store, StoreError, SyncState};
pub use sync::{Event, OVERLAP, Options, Report, sync_platform};

/// Azure DevOps, including the payload types and conversion the tests check directly.
pub mod azure {
    pub use crate::source::azure::types::{PullRequestInfo, Thread};
    pub use crate::source::azure::{Azure, Item, Threads, convert};
}

/// GitHub, including the payload type and conversion the tests check directly.
pub mod github {
    pub use crate::source::github::types::PrNode;
    pub use crate::source::github::{GitHub, convert};
}
