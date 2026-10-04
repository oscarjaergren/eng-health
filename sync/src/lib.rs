//! Syncs pull requests from Azure DevOps and GitHub into the SQLite database
//! that the Python dashboard reads.

pub mod config;
pub mod model;
pub mod rules;
pub mod store;
