//! Pure-Rust compatibility core for the BandoriPet migration.
//!
//! This crate intentionally has no Qt dependency.  Python and native Qt
//! frontends can therefore be checked against the same configuration and IPC
//! contracts while the application is migrated process by process.

pub mod config;
pub mod database;
pub mod ipc;
pub mod model;
