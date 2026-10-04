//! Syncs pull requests from Azure DevOps and GitHub into the SQLite database
//! that the Python dashboard reads.

pub mod config;
pub mod http;
pub mod model;
pub mod rules;
pub mod source;
pub mod store;
pub mod sync;
