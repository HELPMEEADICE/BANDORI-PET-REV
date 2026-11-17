use pet_db::{Database, Result};
use serde_json::{json, Value};

#[test]
fn chat_memory_and_external_domains() -> Result<()> {
    let d = Database::open(std::path::Path::new(":memory:"))?;
    let id = d.call(
        "create_conversation",
        &json!({"character":"灯🐈","user_key":"甲","title":"日本語"}),
    )?;
    d.call("add_message",&json!({"conversation_id":id,"role":"user","content":"中文 100%_\\","reasoning_content":"","attachments_json":"","tool_trace_json":""}))?;
    let records = d.call("search_chat_history", &json!({"keyword":"%_\\"}))?;
    assert_eq!(records["total"], 1);
    assert!(d.call("add_message",&json!({"conversation_id":id,"role":"bad","content":"x","reasoning_content":"","attachments_json":"","tool_trace_json":""})).is_err());
    let a = json!({"character":"灯🐈","user_key":"甲","kind":"note","content":"记忆"});
    assert_eq!(
        d.call("add_character_memory", &a)?,
        d.call("add_character_memory", &a)?
    );
    assert_eq!(
        d.call(
            "get_character_memories",
            &json!({"character":"灯🐈","user_key":"乙"})
        )?,
        json!([])
    );
    let event =
        json!({"event":{"platform":"qq","thread_id":"群","message_id":"1","content":"你好"}});
    assert_eq!(
        d.call("add_external_chat_message", &event)?["duplicate"],
        false
    );
    assert_eq!(
        d.call("add_external_chat_message", &event)?["duplicate"],
        true
    );
    assert_eq!(
        d.call("mark_external_chat_read", &Value::Null)?["marked_read"],
        1
    );
    Ok(())
}
