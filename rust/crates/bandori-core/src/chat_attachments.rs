use crate::database::{Database, DatabaseError, GroupMessage, Message};
use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

pub const MAX_CHAT_ATTACHMENT_BYTES: u64 = 25 * 1024 * 1024;
const MAX_CHAT_ATTACHMENTS_PER_IMPORT: usize = 32;
const FILE_INLINE_BYTES: u64 = 256 * 1024;
const FILE_INLINE_CHARS: usize = 120_000;
const NATIVE_ATTACHMENT_PREFIX: &str = "native-attach-";
const IMAGE_EXTENSIONS: &[&str] = &["png", "jpg", "jpeg", "webp", "gif"];
static ATTACHMENT_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ImportedChatAttachment {
    #[serde(rename = "type")]
    pub attachment_type: String,
    pub path: String,
    pub name: String,
    pub mime: String,
    pub size: u64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct AttachmentImportResult {
    pub attachments: Vec<ImportedChatAttachment>,
    pub errors: Vec<String>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatAttachmentStats {
    pub file_count: u64,
    pub total_bytes: u64,
    pub oldest_uploaded_at_unix: Option<u64>,
    pub newest_uploaded_at_unix: Option<u64>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatAttachmentCleanupResult {
    pub deleted_files: u64,
    pub deleted_bytes: u64,
    pub failed_files: u64,
    pub removed_references: i64,
    pub remaining_files: u64,
    pub remaining_bytes: u64,
}

pub fn chat_attachment_stats(database_path: &Path) -> ChatAttachmentStats {
    attachment_stats_for_root(&chat_attachment_root(database_path))
}

pub fn cleanup_chat_attachments(
    database_path: &Path,
    older_than_days: Option<i64>,
) -> Result<ChatAttachmentCleanupResult, DatabaseError> {
    let root = chat_attachment_root(database_path);
    let cutoff = older_than_days.map(|days| {
        SystemTime::now()
            .checked_sub(std::time::Duration::from_secs(
                days.clamp(1, 3650) as u64 * 24 * 60 * 60,
            ))
            .unwrap_or(UNIX_EPOCH)
    });
    let mut result = ChatAttachmentCleanupResult::default();
    if root.is_dir() {
        for entry in fs::read_dir(&root)? {
            let entry = match entry {
                Ok(entry) => entry,
                Err(_) => {
                    result.failed_files += 1;
                    continue;
                }
            };
            let path = entry.path();
            let metadata = match path.metadata() {
                Ok(metadata) if metadata.is_file() => metadata,
                Ok(_) => continue,
                Err(_) => {
                    result.failed_files += 1;
                    continue;
                }
            };
            if let Some(cutoff) = cutoff {
                let Some(uploaded_at) = attachment_uploaded_at(&metadata) else {
                    result.failed_files += 1;
                    continue;
                };
                if uploaded_at >= cutoff {
                    continue;
                }
            }
            let size = metadata.len();
            match fs::remove_file(&path) {
                Ok(()) => {
                    result.deleted_files += 1;
                    result.deleted_bytes = result.deleted_bytes.saturating_add(size);
                }
                Err(_) => result.failed_files += 1,
            }
        }
    }
    result.removed_references = Database::open(database_path)?.sanitize_attachment_references()?;
    let remaining = attachment_stats_for_root(&root);
    result.remaining_files = remaining.file_count;
    result.remaining_bytes = remaining.total_bytes;
    Ok(result)
}

fn chat_attachment_root(database_path: &Path) -> PathBuf {
    database_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("chat_attachments")
}

fn attachment_stats_for_root(root: &Path) -> ChatAttachmentStats {
    let mut result = ChatAttachmentStats::default();
    let Ok(entries) = fs::read_dir(root) else {
        return result;
    };
    for entry in entries.flatten() {
        let Ok(metadata) = entry.path().metadata() else {
            continue;
        };
        if !metadata.is_file() {
            continue;
        }
        result.file_count += 1;
        result.total_bytes = result.total_bytes.saturating_add(metadata.len());
        if let Some(uploaded_at) = attachment_uploaded_at(&metadata)
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_secs())
        {
            result.oldest_uploaded_at_unix = Some(
                result
                    .oldest_uploaded_at_unix
                    .map(|current| current.min(uploaded_at))
                    .unwrap_or(uploaded_at),
            );
            result.newest_uploaded_at_unix = Some(
                result
                    .newest_uploaded_at_unix
                    .map(|current| current.max(uploaded_at))
                    .unwrap_or(uploaded_at),
            );
        }
    }
    result
}

fn attachment_uploaded_at(metadata: &fs::Metadata) -> Option<SystemTime> {
    match (metadata.created().ok(), metadata.modified().ok()) {
        (Some(created), Some(modified)) => Some(created.max(modified)),
        (Some(created), None) => Some(created),
        (None, Some(modified)) => Some(modified),
        (None, None) => None,
    }
}

pub fn import_chat_attachments(
    database_path: &Path,
    source_paths: &[String],
) -> Result<AttachmentImportResult, DatabaseError> {
    let target_root = database_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("chat_attachments");
    fs::create_dir_all(&target_root)?;
    let mut result = AttachmentImportResult::default();
    for source in source_paths.iter().take(MAX_CHAT_ATTACHMENTS_PER_IMPORT) {
        match import_one(&target_root, Path::new(source)) {
            Ok(attachment) => result.attachments.push(attachment),
            Err(error) => {
                let name = Path::new(source)
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or("attachment");
                result.errors.push(format!("{name}: {error}"));
            }
        }
    }
    if source_paths.len() > MAX_CHAT_ATTACHMENTS_PER_IMPORT {
        result.errors.push(format!(
            "only the first {MAX_CHAT_ATTACHMENTS_PER_IMPORT} attachments were processed"
        ));
    }
    Ok(result)
}

pub fn discard_imported_chat_attachments(
    database_path: &Path,
    attachments: &Value,
) -> Result<usize, DatabaseError> {
    let target_root = database_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("chat_attachments");
    let Ok(safe_root) = target_root.canonicalize() else {
        return Ok(0);
    };
    let Some(items) = attachments.as_array() else {
        return Ok(0);
    };
    let mut removed = 0;
    for item in items {
        let Some(path) = item.get("path").and_then(Value::as_str) else {
            continue;
        };
        let Ok(resolved) = Path::new(path).canonicalize() else {
            continue;
        };
        let is_native_copy = resolved
            .file_name()
            .and_then(|value| value.to_str())
            .is_some_and(|name| name.starts_with(NATIVE_ATTACHMENT_PREFIX));
        if is_native_copy
            && resolved.is_file()
            && resolved.strip_prefix(&safe_root).is_ok()
            && fs::remove_file(resolved).is_ok()
        {
            removed += 1;
        }
    }
    Ok(removed)
}

pub fn chat_message_content(
    database: &Database,
    message: &Message,
    include_raw_images: bool,
) -> Value {
    message_content(
        database,
        &message.content,
        &message.attachments_json,
        include_raw_images,
    )
}

pub fn group_chat_message_content(
    database: &Database,
    message: &GroupMessage,
    include_raw_images: bool,
) -> Value {
    message_content(
        database,
        &message.content,
        &message.attachments_json,
        include_raw_images,
    )
}

fn message_content(
    database: &Database,
    content: &str,
    attachments_json: &str,
    include_raw_images: bool,
) -> Value {
    let attachments = serde_json::from_str::<Value>(attachments_json)
        .ok()
        .and_then(|value| value.as_array().cloned())
        .unwrap_or_default();
    if attachments.is_empty() {
        return Value::String(content.to_owned());
    }
    let mut text = content.to_owned();
    let mut vision_notes = Vec::new();
    let mut file_notes = Vec::new();
    let mut raw_images = Vec::new();
    for attachment in attachments {
        let Some(item) = attachment.as_object() else {
            continue;
        };
        let attachment_type = item.get("type").and_then(Value::as_str).unwrap_or_default();
        let path = item.get("path").and_then(Value::as_str).unwrap_or_default();
        let Some(resolved) = database.resolve_chat_attachment(path) else {
            continue;
        };
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .or_else(|| resolved.file_name().and_then(|value| value.to_str()))
            .unwrap_or("attachment");
        let mime = item
            .get("mime")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| mime_for_path(&resolved, attachment_type == "image"));
        match attachment_type {
            "image" if is_image_path(&resolved) => {
                let summary = trimmed_field(item.get("vision_summary"));
                let error = trimmed_field(item.get("vision_error"));
                if !summary.is_empty() {
                    vision_notes.push(format!("{name}：{summary}"));
                } else if !error.is_empty() {
                    vision_notes.push(format!("{name}：{error}"));
                } else if include_raw_images {
                    if let Ok(bytes) = read_bounded(&resolved, MAX_CHAT_ATTACHMENT_BYTES) {
                        raw_images.push(json!({
                            "type": "image_url",
                            "image_url": {
                                "url": format!(
                                    "data:{mime};base64,{}",
                                    BASE64_STANDARD.encode(bytes)
                                )
                            }
                        }));
                    }
                }
            }
            "file" => file_notes.push(file_attachment_note(&resolved, name, mime, item)),
            _ => {}
        }
    }
    if !vision_notes.is_empty() {
        text.push_str("\n\n【快速视觉模型观察】\n");
        text.push_str(&vision_notes.join("\n"));
    }
    if !file_notes.is_empty() {
        text.push_str("\n\n");
        text.push_str(&file_notes.join("\n\n"));
    }
    if raw_images.is_empty() {
        Value::String(text)
    } else {
        let mut parts = vec![json!({"type": "text", "text": text})];
        parts.extend(raw_images);
        Value::Array(parts)
    }
}

pub fn delete_message_attachment_copies(database: &Database, messages: &[Message]) -> usize {
    delete_attachment_copies(
        database,
        messages
            .iter()
            .map(|message| message.attachments_json.as_str()),
    )
}

pub fn delete_group_message_attachment_copies(
    database: &Database,
    messages: &[GroupMessage],
) -> usize {
    delete_attachment_copies(
        database,
        messages
            .iter()
            .map(|message| message.attachments_json.as_str()),
    )
}

fn delete_attachment_copies<'a>(
    database: &Database,
    attachments_json: impl IntoIterator<Item = &'a str>,
) -> usize {
    let mut paths = HashSet::new();
    for source in attachments_json {
        let attachments = serde_json::from_str::<Value>(source)
            .ok()
            .and_then(|value| value.as_array().cloned())
            .unwrap_or_default();
        for attachment in attachments {
            let Some(path) = attachment.get("path").and_then(Value::as_str) else {
                continue;
            };
            if let Some(resolved) = database.resolve_chat_attachment(path) {
                paths.insert(resolved);
            }
        }
    }
    paths
        .into_iter()
        .filter(|path| fs::remove_file(path).is_ok())
        .count()
}

fn import_one(target_root: &Path, source: &Path) -> io::Result<ImportedChatAttachment> {
    let source = source.canonicalize()?;
    let metadata = source.metadata()?;
    if !metadata.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "not a regular file",
        ));
    }
    if metadata.len() > MAX_CHAT_ATTACHMENT_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "attachment exceeds the 25 MB limit",
        ));
    }
    let original_name = source
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("attachment");
    let extension = safe_extension(&source);
    let (target, mut output) = create_unique_target(target_root, &extension)?;
    let copy_result = (|| -> io::Result<u64> {
        let input = File::open(&source)?;
        let mut limited = input.take(MAX_CHAT_ATTACHMENT_BYTES + 1);
        let copied = io::copy(&mut limited, &mut output)?;
        output.flush()?;
        Ok(copied)
    })();
    drop(output);
    let copied = match copy_result {
        Ok(copied) => copied,
        Err(error) => {
            let _ = fs::remove_file(&target);
            return Err(error);
        }
    };
    if copied > MAX_CHAT_ATTACHMENT_BYTES {
        let _ = fs::remove_file(&target);
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "attachment changed while copying and exceeded the 25 MB limit",
        ));
    }
    let is_image = IMAGE_EXTENSIONS.contains(&extension.as_str());
    Ok(ImportedChatAttachment {
        attachment_type: if is_image { "image" } else { "file" }.to_owned(),
        path: target.to_string_lossy().into_owned(),
        name: original_name.chars().take(240).collect(),
        mime: mime_for_extension(&extension, is_image).to_owned(),
        size: copied,
    })
}

fn create_unique_target(target_root: &Path, extension: &str) -> io::Result<(PathBuf, File)> {
    for _ in 0..32 {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let sequence = ATTACHMENT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let suffix = if extension.is_empty() {
            String::new()
        } else {
            format!(".{extension}")
        };
        let target = target_root.join(format!(
            "{NATIVE_ATTACHMENT_PREFIX}{nanos:x}-{:x}-{sequence:x}{suffix}",
            std::process::id()
        ));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
        {
            Ok(file) => return Ok((target, file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "could not allocate a unique attachment name",
    ))
}

fn file_attachment_note(
    path: &Path,
    name: &str,
    mime: &str,
    item: &serde_json::Map<String, Value>,
) -> String {
    let size = item
        .get("size")
        .and_then(Value::as_i64)
        .and_then(|value| u64::try_from(value).ok())
        .or_else(|| path.metadata().ok().map(|metadata| metadata.len()));
    let mut header = vec![
        "【文件附件】".to_owned(),
        format!("文件名：{name}"),
        format!("MIME：{mime}"),
    ];
    if let Some(size) = size {
        header.push(format!("大小：{}", format_attachment_size(size)));
    }
    if !is_text_attachment(path, mime) {
        header.push("内容：该文件不是可直接内联的文本文件，已作为附件元信息提供。".to_owned());
        return header.join("\n");
    }
    let bytes = (|| -> io::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        File::open(path)?
            .take(FILE_INLINE_BYTES + 1)
            .read_to_end(&mut bytes)?;
        Ok(bytes)
    })();
    let Ok(bytes) = bytes else {
        header.push("内容：文件读取失败。".to_owned());
        return header.join("\n");
    };
    let mut truncated = bytes.len() as u64 > FILE_INLINE_BYTES;
    let bytes = &bytes[..bytes.len().min(FILE_INLINE_BYTES as usize)];
    let bytes = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(bytes);
    let mut text = String::from_utf8_lossy(bytes).into_owned();
    if text.chars().count() > FILE_INLINE_CHARS {
        text = text.chars().take(FILE_INLINE_CHARS).collect();
        truncated = true;
    }
    let language = path
        .extension()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("text");
    header.push(format!("内容：\n```{language}\n{text}\n```"));
    let mut note = header.join("\n");
    if truncated {
        note.push_str("\n（内容已截断）");
    }
    note
}

fn read_bounded(path: &Path, limit: u64) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    File::open(path)?.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "attachment exceeded the read limit",
        ));
    }
    Ok(bytes)
}

fn safe_extension(path: &Path) -> String {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if extension.len() <= 16 && extension.chars().all(|value| value.is_ascii_alphanumeric()) {
        extension
    } else {
        String::new()
    }
}

fn mime_for_path(path: &Path, is_image: bool) -> &'static str {
    mime_for_extension(&safe_extension(path), is_image)
}

fn mime_for_extension(extension: &str, is_image: bool) -> &'static str {
    match extension {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "txt" | "md" | "markdown" | "csv" | "tsv" | "log" => "text/plain",
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "json" | "jsonl" => "application/json",
        "xml" => "application/xml",
        "yaml" | "yml" => "application/yaml",
        "js" | "jsx" => "application/javascript",
        "sql" => "application/sql",
        _ if is_image => "image/png",
        _ => "application/octet-stream",
    }
}

fn is_image_path(path: &Path) -> bool {
    IMAGE_EXTENSIONS.contains(&safe_extension(path).as_str())
}

fn is_text_attachment(path: &Path, mime: &str) -> bool {
    const TEXT_EXTENSIONS: &[&str] = &[
        "txt",
        "md",
        "markdown",
        "csv",
        "tsv",
        "json",
        "jsonl",
        "yaml",
        "yml",
        "xml",
        "html",
        "htm",
        "css",
        "js",
        "jsx",
        "ts",
        "tsx",
        "py",
        "java",
        "c",
        "cc",
        "cpp",
        "h",
        "hpp",
        "cs",
        "go",
        "rs",
        "rb",
        "php",
        "swift",
        "kt",
        "kts",
        "sh",
        "bash",
        "zsh",
        "ps1",
        "bat",
        "cmd",
        "sql",
        "ini",
        "cfg",
        "conf",
        "toml",
        "log",
        "po",
        "pot",
        "properties",
    ];
    let mime = mime.split(';').next().unwrap_or_default().trim();
    TEXT_EXTENSIONS.contains(&safe_extension(path).as_str())
        || mime.starts_with("text/")
        || matches!(
            mime,
            "application/json"
                | "application/xml"
                | "application/yaml"
                | "application/x-yaml"
                | "application/javascript"
                | "application/x-javascript"
                | "application/sql"
        )
}

fn format_attachment_size(size: u64) -> String {
    if size < 1024 {
        format!("{size} B")
    } else if size < 1024 * 1024 {
        format!("{:.1} KB", size as f64 / 1024.0)
    } else {
        format!("{:.1} MB", size as f64 / (1024.0 * 1024.0))
    }
}

fn trimmed_field(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn imports_bounded_copies_and_discards_only_native_pending_files() {
        let directory = tempfile::tempdir().unwrap();
        let database_path = directory.path().join("data.db");
        let source = directory.path().join("notes.md");
        fs::write(&source, "hello attachment").unwrap();
        let result =
            import_chat_attachments(&database_path, &[source.to_string_lossy().into_owned()])
                .unwrap();
        assert!(result.errors.is_empty());
        assert_eq!(result.attachments.len(), 1);
        let attachment = &result.attachments[0];
        assert_eq!(attachment.attachment_type, "file");
        assert_eq!(attachment.mime, "text/plain");
        assert_eq!(
            fs::read_to_string(&attachment.path).unwrap(),
            "hello attachment"
        );
        assert!(source.exists());
        let removed = discard_imported_chat_attachments(
            &database_path,
            &serde_json::to_value(&result.attachments).unwrap(),
        )
        .unwrap();
        assert_eq!(removed, 1);
        assert!(!Path::new(&attachment.path).exists());
        assert!(source.exists());
    }

    #[test]
    fn latest_message_inlines_text_files_and_raw_images() {
        let directory = tempfile::tempdir().unwrap();
        let database_path = directory.path().join("data.db");
        let attachment_root = directory.path().join("chat_attachments");
        fs::create_dir(&attachment_root).unwrap();
        let note = attachment_root.join("note.rs");
        let image = attachment_root.join("pixel.png");
        fs::write(&note, "fn main() {}\n").unwrap();
        fs::write(&image, b"PNG fixture").unwrap();
        let database = Database::open(&database_path).unwrap();
        let turn = database
            .begin_private_chat_turn(
                "ran",
                "alice",
                None,
                "inspect",
                Some(&json!([
                    {"type":"file","path":note,"name":"note.rs","mime":"text/plain","size":13},
                    {"type":"image","path":image,"name":"pixel.png","mime":"image/png","size":11}
                ])),
            )
            .unwrap();
        let message = database
            .get_messages(turn.conversation_id, None, None)
            .unwrap()
            .remove(0);
        let content = chat_message_content(&database, &message, true);
        let parts = content.as_array().unwrap();
        assert!(
            parts[0]["text"]
                .as_str()
                .unwrap()
                .contains("```rs\nfn main() {}")
        );
        assert!(
            parts[1]["image_url"]["url"]
                .as_str()
                .unwrap()
                .starts_with("data:image/png;base64,")
        );
        assert!(chat_message_content(&database, &message, false).is_string());
    }

    #[test]
    fn oversized_text_preview_is_truncated_instead_of_reported_as_unreadable() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("large.txt");
        fs::write(&path, vec![b'a'; FILE_INLINE_BYTES as usize + 10]).unwrap();
        let note = file_attachment_note(&path, "large.txt", "text/plain", &Default::default());
        assert!(note.contains("```txt\n"));
        assert!(note.ends_with("（内容已截断）"));
        assert!(!note.contains("读取失败"));
    }

    #[test]
    fn attachment_stats_and_cleanup_are_scoped_to_the_database_directory() {
        let directory = tempfile::tempdir().unwrap();
        let database_path = directory.path().join("data.db");
        let root = directory.path().join("chat_attachments");
        fs::create_dir(&root).unwrap();
        fs::write(root.join("one.txt"), b"one").unwrap();
        fs::write(root.join("two.txt"), b"second").unwrap();
        let outside = directory.path().join("outside.txt");
        fs::write(&outside, b"outside").unwrap();
        let database = Database::open(&database_path).unwrap();
        let conversation = database.create_conversation("Ran", "", "").unwrap();
        database
            .add_message(
                conversation,
                "user",
                "attachment",
                "",
                Some(&json!([{"type": "file", "path": root.join("one.txt")}])),
                None,
            )
            .unwrap();

        let stats = chat_attachment_stats(&database_path);
        assert_eq!(stats.file_count, 2);
        assert_eq!(stats.total_bytes, 9);
        let retained = cleanup_chat_attachments(&database_path, Some(1)).unwrap();
        assert_eq!(retained.deleted_files, 0);
        let cleared = cleanup_chat_attachments(&database_path, None).unwrap();
        assert_eq!(cleared.deleted_files, 2);
        assert_eq!(cleared.deleted_bytes, 9);
        assert_eq!(cleared.removed_references, 1);
        assert_eq!(cleared.remaining_files, 0);
        assert_eq!(
            database.get_messages(conversation, None, None).unwrap()[0].attachments_json,
            ""
        );
        assert!(outside.exists());
    }
}
