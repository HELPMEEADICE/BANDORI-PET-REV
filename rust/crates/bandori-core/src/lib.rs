//! Pure-Rust compatibility core for the BandoriPet migration.
//!
//! This crate intentionally has no Qt dependency.  Python and native Qt
//! frontends can therefore be checked against the same configuration and IPC
//! contracts while the application is migrated process by process.

pub mod chat_actions;
pub mod chat_attachments;
pub mod chat_context;
pub mod chat_dashboard;
pub mod chat_management;
pub mod chat_prompt;
pub mod chat_tools;
pub mod config;
pub mod config_ffi;
pub mod cross_chat_history;
pub mod dashboard;
pub mod database;
pub mod group_chat;
pub mod ipc;
pub mod ipc_ffi;
pub mod llm_settings;
pub mod memory_dashboard;
pub mod memory_extraction;
pub mod model;
pub mod relationship_analysis;
pub mod reminder;
pub mod user_profiles;

pub use bandori_llm_protocol as llm_protocol;
