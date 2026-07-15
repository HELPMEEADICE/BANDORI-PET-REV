//! Pure-Rust compatibility core for the BandoriPet migration.
//!
//! This crate intentionally has no Qt dependency.  Python and native Qt
//! frontends can therefore be checked against the same configuration and IPC
//! contracts while the application is migrated process by process.

pub mod chat_actions;
pub mod chat_context;
pub mod chat_dashboard;
pub mod chat_prompt;
pub mod config;
pub mod config_ffi;
pub mod dashboard;
pub mod database;
pub mod ipc;
pub mod ipc_ffi;
pub mod memory_extraction;
pub mod model;
pub mod relationship_analysis;

pub use bandori_llm_protocol as llm_protocol;
