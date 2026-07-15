use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha1::{Digest, Sha1};
use std::collections::HashMap;
use thiserror::Error;

pub const MAGIC: &[u8; 8] = b"BDIPC01!";
pub const VERSION: u32 = 1;
pub const HEADER_SIZE: usize = 28;
pub const SLOT_HEADER_SIZE: usize = 12;
pub const DEFAULT_SLOT_COUNT: usize = 8;
pub const DEFAULT_SLOT_SIZE: usize = 65_536;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct QueueHeader {
    pub version: u32,
    pub slot_count: u32,
    pub slot_size: u32,
    pub next_sequence: u64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ReadBatch {
    pub messages: Vec<String>,
    pub dropped: u64,
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum QueueError {
    #[error("shared-memory queue buffer is too small")]
    BufferTooSmall,
    #[error("shared-memory queue header is invalid")]
    InvalidHeader,
    #[error("shared-memory queue payload is empty")]
    EmptyPayload,
    #[error("shared-memory queue payload exceeds {slot_size} bytes")]
    PayloadTooLarge { slot_size: usize },
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct IpcEnvelope {
    pub sender_id: String,
    pub line: String,
    pub exclude_peer_id: String,
    pub message_id: String,
    pub reliable: bool,
}

#[derive(Serialize)]
struct EncodedEnvelope<'a> {
    sender: &'a str,
    exclude: &'a str,
    line: &'a str,
    message_id: &'a str,
    reliable: bool,
}

#[derive(Deserialize)]
struct DecodedEnvelope {
    #[serde(default)]
    sender: Value,
    #[serde(default)]
    exclude: Value,
    #[serde(default)]
    line: Value,
    #[serde(default)]
    message_id: Value,
    #[serde(default)]
    reliable: Value,
}

pub fn normalize_line(line: &str) -> &str {
    line.trim_end_matches(['\r', '\n'])
}

pub fn encode_envelope(envelope: &IpcEnvelope) -> String {
    serde_json::to_string(&EncodedEnvelope {
        sender: &envelope.sender_id,
        exclude: &envelope.exclude_peer_id,
        line: normalize_line(&envelope.line),
        message_id: &envelope.message_id,
        reliable: envelope.reliable,
    })
    .expect("serializing an IPC envelope cannot fail")
}

pub fn decode_envelope(raw: &str) -> IpcEnvelope {
    let Ok(decoded) = serde_json::from_str::<DecodedEnvelope>(raw) else {
        return IpcEnvelope {
            line: normalize_line(raw).to_owned(),
            ..IpcEnvelope::default()
        };
    };

    IpcEnvelope {
        sender_id: python_string(&decoded.sender),
        line: normalize_line(&python_string(&decoded.line)).to_owned(),
        exclude_peer_id: python_string(&decoded.exclude),
        message_id: python_string(&decoded.message_id),
        reliable: truthy(&decoded.reliable),
    }
}

pub fn make_shared_memory_key(parts: &[&str]) -> String {
    let raw = parts.join("::");
    let digest = format!("{:x}", Sha1::digest(raw.as_bytes()));
    let label_source = parts
        .iter()
        .rev()
        .take(2)
        .copied()
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("-");
    let label = label_source
        .chars()
        .map(|ch| {
            if ch.is_alphanumeric() || matches!(ch, '.' | '_' | '-') {
                ch
            } else {
                '-'
            }
        })
        .take(48)
        .collect::<String>();
    format!(
        "BandoriPet-{}-{}",
        if label.is_empty() { "ipc" } else { &label },
        &digest[..16]
    )
}

pub fn queue_memory_size(slot_count: usize, slot_size: usize) -> Option<usize> {
    slot_count
        .checked_mul(SLOT_HEADER_SIZE.checked_add(slot_size)?)?
        .checked_add(HEADER_SIZE)
}

pub fn initialize_queue(
    memory: &mut [u8],
    slot_count: usize,
    slot_size: usize,
) -> Result<(), QueueError> {
    if slot_count == 0 || slot_size == 0 {
        return Err(QueueError::InvalidHeader);
    }
    let required = queue_memory_size(slot_count, slot_size).ok_or(QueueError::BufferTooSmall)?;
    if memory.len() < required {
        return Err(QueueError::BufferTooSmall);
    }
    memory[..required].fill(0);
    memory[..8].copy_from_slice(MAGIC);
    write_u32(memory, 8, VERSION);
    write_u32(memory, 12, slot_count as u32);
    write_u32(memory, 16, slot_size as u32);
    write_u64(memory, 20, 0);
    Ok(())
}

pub fn read_queue_header(memory: &[u8]) -> Result<QueueHeader, QueueError> {
    if memory.len() < HEADER_SIZE || &memory[..8] != MAGIC {
        return Err(QueueError::InvalidHeader);
    }
    let header = QueueHeader {
        version: read_u32(memory, 8),
        slot_count: read_u32(memory, 12),
        slot_size: read_u32(memory, 16),
        next_sequence: read_u64(memory, 20),
    };
    let required = queue_memory_size(header.slot_count as usize, header.slot_size as usize)
        .ok_or(QueueError::InvalidHeader)?;
    if header.version != VERSION
        || header.slot_count == 0
        || header.slot_size == 0
        || memory.len() < required
    {
        return Err(QueueError::InvalidHeader);
    }
    Ok(header)
}

pub fn publish(memory: &mut [u8], line: &str) -> Result<u64, QueueError> {
    let payload = normalize_line(line).as_bytes();
    if payload.is_empty() {
        return Err(QueueError::EmptyPayload);
    }
    let header = read_queue_header(memory)?;
    if payload.len() > header.slot_size as usize {
        return Err(QueueError::PayloadTooLarge {
            slot_size: header.slot_size as usize,
        });
    }

    let sequence = header.next_sequence;
    let slot_index = sequence as usize % header.slot_count as usize;
    let offset = HEADER_SIZE + slot_index * (SLOT_HEADER_SIZE + header.slot_size as usize);
    write_u64(memory, offset, sequence);
    write_u32(memory, offset + 8, payload.len() as u32);
    let payload_start = offset + SLOT_HEADER_SIZE;
    memory[payload_start..payload_start + payload.len()].copy_from_slice(payload);
    write_u64(memory, 20, sequence + 1);
    Ok(sequence)
}

pub fn read_available(
    memory: &[u8],
    cursor: &mut u64,
    max_messages: Option<usize>,
) -> Result<ReadBatch, QueueError> {
    let header = read_queue_header(memory)?;
    if max_messages == Some(0) {
        return Ok(ReadBatch::default());
    }

    let first_available = header
        .next_sequence
        .saturating_sub(header.slot_count as u64);
    let dropped = first_available.saturating_sub(*cursor);
    *cursor = (*cursor).max(first_available);

    let mut messages = Vec::new();
    while *cursor < header.next_sequence && max_messages.is_none_or(|limit| messages.len() < limit)
    {
        let slot_index = *cursor as usize % header.slot_count as usize;
        let offset = HEADER_SIZE + slot_index * (SLOT_HEADER_SIZE + header.slot_size as usize);
        let slot_sequence = read_u64(memory, offset);
        let length = read_u32(memory, offset + 8) as usize;
        if slot_sequence == *cursor && length > 0 && length <= header.slot_size as usize {
            let payload_start = offset + SLOT_HEADER_SIZE;
            messages.push(
                String::from_utf8_lossy(&memory[payload_start..payload_start + length])
                    .into_owned(),
            );
        }
        *cursor += 1;
    }
    Ok(ReadBatch { messages, dropped })
}

pub fn is_control_line(line: &str) -> bool {
    let line = normalize_line(line);
    line == "SHUTDOWN"
        || [
            "SETTINGS\t",
            "FOCUS_CHAT",
            "FOCUS_SETTINGS",
            "OPEN_CHAT",
            "SHOW_COSTUMES",
        ]
        .iter()
        .any(|prefix| line.starts_with(prefix))
}

pub fn is_reliable_line(line: &str) -> bool {
    let line = normalize_line(line);
    is_control_line(line)
        || [
            "REGISTER\t",
            "UNREGISTER\t",
            "PEER_OFFLINE\t",
            "PEER_DRAG_END\t",
            "RADIAL_MENU_OPEN\t",
            "RADIAL_MENU_CLOSED\t",
            "MODEL\t",
            "PET_STATE\t",
            "LAUNCH",
            "EXIT",
            "OPEN_SETTINGS",
            "POKE_USER\t",
            "CHAT_EVENT\t",
            "REMINDER_EVENT\t",
        ]
        .iter()
        .any(|prefix| line.starts_with(prefix))
}

pub fn coalesce_latest_peer_positions(raw_lines: &[String]) -> Vec<String> {
    let mut stream_keys = Vec::with_capacity(raw_lines.len());
    let mut latest = HashMap::<String, usize>::new();

    for (index, raw) in raw_lines.iter().enumerate() {
        let line = decode_envelope(raw).line;
        let stream_key = peer_stream_key(&line);
        if let Some(key) = &stream_key {
            latest.insert(key.clone(), index);
        }
        stream_keys.push(stream_key);
    }

    raw_lines
        .iter()
        .enumerate()
        .filter(|(index, _)| {
            stream_keys[*index]
                .as_ref()
                .is_none_or(|key| latest.get(key) == Some(index))
        })
        .map(|(_, line)| line.clone())
        .collect()
}

fn peer_stream_key(line: &str) -> Option<String> {
    let (event, payload) = line.split_once('\t')?;
    if !matches!(event, "PEER_POS" | "PEER_DRAG") {
        return None;
    }
    let payload = serde_json::from_str::<Value>(payload).ok()?;
    let object = payload.as_object()?;
    let character = object.get("character")?.as_str()?.trim();
    if character.is_empty() {
        return None;
    }
    if event == "PEER_POS" {
        return Some(format!("position:{character}"));
    }
    let drag_id = object.get("drag_id")?.as_str()?.trim();
    (!drag_id.is_empty()).then(|| format!("drag:{character}:{drag_id}"))
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => String::new(),
        Value::Number(number) if number.as_f64().is_some_and(|number| number == 0.0) => {
            String::new()
        }
        Value::Number(number) => number.to_string(),
        Value::String(value) => value.clone(),
        Value::Array(value) if value.is_empty() => String::new(),
        Value::Object(value) if value.is_empty() => String::new(),
        other => other.to_string(),
    }
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn read_u32(memory: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(
        memory[offset..offset + 4]
            .try_into()
            .expect("checked header"),
    )
}

fn read_u64(memory: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(
        memory[offset..offset + 8]
            .try_into()
            .expect("checked header"),
    )
}

fn write_u32(memory: &mut [u8], offset: usize, value: u32) {
    memory[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn write_u64(memory: &mut [u8], offset: usize, value: u64) {
    memory[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[test]
    fn shared_memory_key_matches_python() {
        assert_eq!(
            make_shared_memory_key(&["bandori-main-123", "main-in"]),
            "BandoriPet-bandori-main-123-main-in-e366281215707911"
        );
    }

    #[test]
    fn envelope_wire_shape_and_unicode_match_python() {
        let envelope = IpcEnvelope {
            sender_id: "pet-1".into(),
            line: "SETTINGS\t{\"语言\":\"中文\"}\r\n".into(),
            exclude_peer_id: "pet-2".into(),
            message_id: "m-1".into(),
            reliable: true,
        };
        let encoded = encode_envelope(&envelope);
        assert_eq!(
            encoded,
            "{\"sender\":\"pet-1\",\"exclude\":\"pet-2\",\"line\":\"SETTINGS\\t{\\\"语言\\\":\\\"中文\\\"}\",\"message_id\":\"m-1\",\"reliable\":true}"
        );
        assert_eq!(
            decode_envelope(&encoded),
            IpcEnvelope {
                line: normalize_line(&envelope.line).into(),
                ..envelope
            }
        );
    }

    #[test]
    fn reliable_classifier_matches_control_contract() {
        assert!(is_reliable_line("SETTINGS\t{}"));
        assert!(is_reliable_line("CHAT_EVENT\t{}"));
        assert!(is_reliable_line("PET_STATE\t{}"));
        assert!(!is_reliable_line("PEER_POS\t{}"));
    }

    #[test]
    fn peer_updates_keep_only_latest_stream_value() {
        let lines = vec![
            "PEER_POS\t{\"character\":\"Ran\",\"x\":1}".to_owned(),
            "CHAT_EVENT\t{}".to_owned(),
            "PEER_POS\t{\"character\":\"Ran\",\"x\":2}".to_owned(),
        ];
        assert_eq!(
            coalesce_latest_peer_positions(&lines),
            vec![lines[1].clone(), lines[2].clone()]
        );
    }

    #[derive(Deserialize)]
    struct IpcVectors {
        keys: Vec<KeyVector>,
        envelope: EnvelopeVector,
        classification: Vec<ClassificationVector>,
        coalesce: CoalesceVector,
        queue_layout: QueueLayoutVector,
    }

    #[derive(Deserialize)]
    struct KeyVector {
        parts: Vec<String>,
        expected: String,
    }

    #[derive(Deserialize)]
    struct EnvelopeVector {
        fields: EnvelopeFields,
        expected: String,
    }

    #[derive(Deserialize)]
    struct EnvelopeFields {
        sender_id: String,
        line: String,
        exclude_peer_id: String,
        message_id: String,
        reliable: bool,
    }

    #[derive(Deserialize)]
    struct ClassificationVector {
        line: String,
        control: bool,
        reliable: bool,
    }

    #[derive(Deserialize)]
    struct CoalesceVector {
        input: Vec<String>,
        expected: Vec<String>,
    }

    #[derive(Deserialize)]
    struct QueueLayoutVector {
        slot_count: usize,
        slot_size: usize,
        messages: Vec<String>,
        expected_hex: String,
    }

    fn vectors() -> IpcVectors {
        serde_json::from_str(include_str!("../../../compat/ipc_vectors.json")).unwrap()
    }

    #[test]
    fn generated_python_vectors_match_rust_protocol() {
        let vectors = vectors();
        for vector in vectors.keys {
            let parts = vector.parts.iter().map(String::as_str).collect::<Vec<_>>();
            assert_eq!(make_shared_memory_key(&parts), vector.expected);
        }

        let fields = vectors.envelope.fields;
        assert_eq!(
            encode_envelope(&IpcEnvelope {
                sender_id: fields.sender_id,
                line: fields.line,
                exclude_peer_id: fields.exclude_peer_id,
                message_id: fields.message_id,
                reliable: fields.reliable,
            }),
            vectors.envelope.expected
        );
        for vector in vectors.classification {
            assert_eq!(is_control_line(&vector.line), vector.control);
            assert_eq!(is_reliable_line(&vector.line), vector.reliable);
        }
        assert_eq!(
            coalesce_latest_peer_positions(&vectors.coalesce.input),
            vectors.coalesce.expected
        );
    }

    #[test]
    fn queue_bytes_match_python_struct_layout() {
        let vector = vectors().queue_layout;
        let mut memory = vec![0; queue_memory_size(vector.slot_count, vector.slot_size).unwrap()];
        initialize_queue(&mut memory, vector.slot_count, vector.slot_size).unwrap();
        for message in vector.messages {
            publish(&mut memory, &message).unwrap();
        }
        let actual = memory
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        assert_eq!(actual, vector.expected_hex);
    }

    #[test]
    fn queue_overflow_reports_dropped_messages() {
        let mut memory = vec![0; queue_memory_size(2, 16).unwrap()];
        initialize_queue(&mut memory, 2, 16).unwrap();
        publish(&mut memory, "one").unwrap();
        publish(&mut memory, "two").unwrap();
        publish(&mut memory, "three").unwrap();

        let mut cursor = 0;
        let batch = read_available(&memory, &mut cursor, None).unwrap();
        assert_eq!(batch.dropped, 1);
        assert_eq!(batch.messages, ["two", "three"]);
        assert_eq!(cursor, 3);
    }
}
