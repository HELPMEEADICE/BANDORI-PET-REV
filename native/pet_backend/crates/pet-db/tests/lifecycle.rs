use pet_db::Database;
use serde_json::json;

#[test]
fn schema_reopen_and_integrity() -> pet_db::Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("数据.db");
    let db = Database::open(&path)?;
    assert_eq!(db.call("integrity_check", &json!({}))?, json!("ok"));
    db.close()?;
    assert!(db.call("integrity_check", &json!({})).is_err());
    let db = Database::open(&path)?;
    assert_eq!(db.call("integrity_check", &json!({}))?, json!("ok"));
    Ok(())
}

#[test]
fn error_rolls_back_transaction() -> pet_db::Result<()> {
    let db = Database::open(std::path::Path::new(":memory:"))?;
    db.with_connection(|c| {
        let result: pet_db::Result<()> = Database::transaction(c, true, |c| {
            c.execute("INSERT INTO conversations(character) VALUES ('灯')", [])?;
            c.execute(
                "INSERT INTO messages(conversation_id,role,content) VALUES (1,'bad','x')",
                [],
            )?;
            Ok(())
        });
        assert!(result.is_err());
        assert_eq!(
            c.query_row("SELECT count(*) FROM conversations", [], |r| r
                .get::<_, i64>(0))?,
            0
        );
        Ok(())
    })
}
