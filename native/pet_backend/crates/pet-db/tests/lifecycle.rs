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

#[test]
fn failed_schema_upgrade_is_atomic() -> pet_db::Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("incompatible.db");
    {
        let c = rusqlite::Connection::open(&path)?;
        c.execute_batch("CREATE TABLE conversations(id INTEGER PRIMARY KEY,custom TEXT);INSERT INTO conversations VALUES(7,'preserve');")?;
    }
    assert!(Database::open(&path).is_err());
    let c = rusqlite::Connection::open(&path)?;
    assert_eq!(
        c.query_row("SELECT custom FROM conversations WHERE id=7", [], |r| {
            r.get::<_, String>(0)
        })?,
        "preserve"
    );
    assert_eq!(
        c.query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'",
            [],
            |r| r.get::<_, i64>(0)
        )?,
        1
    );
    Ok(())
}

#[test]
fn online_backup_and_live_restore_keep_file_compatible() -> pet_db::Result<()> {
    let dir = tempfile::tempdir()?;
    let source = dir.path().join("source.db");
    let target = dir.path().join("target.db");
    let backup = dir.path().join("backup.db");
    let src = Database::open(&source)?;
    let dst = Database::open(&target)?;
    src.call(
        "create_conversation",
        &json!({"character":"中文🐈","title":"日本語"}),
    )?;
    pet_db::maintenance::snapshot(&source, &backup, true)?;
    dst.restore(&backup)?;
    assert_eq!(
        dst.call("get_chat_summary", &json!({}))?["total_conversations"],
        1
    );
    assert_eq!(dst.call("integrity_check", &json!({}))?, "ok");
    Ok(())
}
