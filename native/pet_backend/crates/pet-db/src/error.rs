#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Invalid(String),
    #[error("Cannot operate on a closed database.")]
    Closed,
    #[error("database connection mutex poisoned")]
    Poisoned,
    #[error("database handle belongs to a different process; reopen after fork")]
    Process,
}

pub type Result<T> = std::result::Result<T, Error>;
