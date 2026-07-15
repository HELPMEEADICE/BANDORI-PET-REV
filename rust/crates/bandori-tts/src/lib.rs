use futures_util::StreamExt;
use reqwest::{Client, Response, StatusCode};
use serde_json::{Map, Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use thiserror::Error;
use tokio_util::sync::CancellationToken;

const MAX_TTS_TEXT_BYTES: usize = 64 * 1024;
const MAX_AUDIO_BYTES: usize = 64 * 1024 * 1024;
const MAX_AUDIO_CHUNK_BYTES: usize = 16 * 1024 * 1024;
const MAX_ERROR_BODY_BYTES: usize = 64 * 1024;
const MAX_DIALOG_JSON_BYTES: u64 = 2 * 1024 * 1024;
const DEFAULT_TTS_URL: &str = "http://127.0.0.1:9880/";
const REFERENCE_EXTENSIONS: &[&str] = &["mp3", "wav", "flac", "ogg", "m4a"];

#[derive(Clone, Debug, PartialEq)]
pub struct TtsConfig {
    pub api_url: String,
    pub language: String,
    pub reference_character: String,
    pub streaming: bool,
    pub temperature: f64,
    pub project_root: PathBuf,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TtsRequest {
    pub text: String,
    pub character: String,
    pub speed_factor: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PreparedTtsRequest {
    pub endpoint: String,
    pub payload: Value,
    pub prepared_text: String,
    pub language: String,
    pub lora_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TtsAudioChunk {
    pub bytes: Vec<u8>,
    pub media_type: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TtsOutcome {
    pub chunk_count: usize,
    pub total_bytes: usize,
    pub used_streaming: bool,
    pub prepared_text: String,
    pub language: String,
}

#[derive(Debug, Error)]
pub enum TtsError {
    #[error("TTS request was cancelled")]
    Cancelled,
    #[error("invalid TTS request: {0}")]
    InvalidRequest(String),
    #[error("TTS transport failed: {0}")]
    Http(&'static str),
    #[error("TTS endpoint returned HTTP {status}: {message}")]
    HttpStatus { status: u16, message: String },
    #[error("TTS audio response exceeded the {MAX_AUDIO_BYTES} byte limit")]
    AudioTooLarge,
    #[error("TTS framed stream declared an invalid audio chunk")]
    InvalidFramedChunk,
    #[error("TTS framed stream ended inside an audio chunk")]
    IncompleteFramedStream,
}

#[derive(Clone, Debug)]
pub struct TtsTransport {
    client: Client,
    config: TtsConfig,
}

impl TtsTransport {
    pub fn new(config: TtsConfig) -> Result<Self, TtsError> {
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(15))
            .timeout(Duration::from_secs(120))
            .build()
            .map_err(|_| TtsError::Http("could not create HTTP client"))?;
        Ok(Self { client, config })
    }

    pub async fn synthesize<F>(
        &self,
        request: &TtsRequest,
        cancellation: &CancellationToken,
        mut on_audio: F,
    ) -> Result<TtsOutcome, TtsError>
    where
        F: FnMut(TtsAudioChunk),
    {
        let prepared = prepare_tts_request(&self.config, request)?;
        let mut payload = prepared.payload.clone();
        self.apply_available_lora(&prepared, &mut payload, cancellation)
            .await;
        let mut modes = vec![self.config.streaming];
        if self.config.streaming {
            modes.push(false);
        }
        let mut last_stream_error = None;
        for streaming in modes {
            configure_media_payload(&mut payload, streaming);
            let mut response = self
                .send(&prepared.endpoint, &payload, cancellation)
                .await?;
            if !response.status().is_success() && payload.get("speed_factor").is_some() {
                payload
                    .as_object_mut()
                    .expect("payload is an object")
                    .remove("speed_factor");
                response = self
                    .send(&prepared.endpoint, &payload, cancellation)
                    .await?;
            }
            if !response.status().is_success() {
                let status = response.status();
                let message = read_error_body(response, cancellation).await?;
                if streaming && streaming_failure_is_incompatible(status) {
                    last_stream_error = Some((status.as_u16(), message));
                    continue;
                }
                return Err(TtsError::HttpStatus {
                    status: status.as_u16(),
                    message,
                });
            }
            match consume_audio_response(response, streaming, cancellation, &mut on_audio).await {
                Ok((chunk_count, total_bytes)) => {
                    return Ok(TtsOutcome {
                        chunk_count,
                        total_bytes,
                        used_streaming: streaming,
                        prepared_text: prepared.prepared_text,
                        language: prepared.language,
                    });
                }
                Err(TtsError::Cancelled) => return Err(TtsError::Cancelled),
                Err(error) if streaming => {
                    last_stream_error = Some((0, error.to_string()));
                }
                Err(error) => return Err(error),
            }
        }
        let (status, message) = last_stream_error.unwrap_or_else(|| {
            (
                0,
                "streaming and fallback requests returned no audio".into(),
            )
        });
        Err(TtsError::HttpStatus { status, message })
    }

    async fn send(
        &self,
        endpoint: &str,
        payload: &Value,
        cancellation: &CancellationToken,
    ) -> Result<Response, TtsError> {
        tokio::select! {
            _ = cancellation.cancelled() => Err(TtsError::Cancelled),
            response = self.client.post(endpoint).json(payload).send() => {
                response.map_err(|_| TtsError::Http("request failed"))
            }
        }
    }

    async fn apply_available_lora(
        &self,
        prepared: &PreparedTtsRequest,
        payload: &mut Value,
        cancellation: &CancellationToken,
    ) {
        if cancellation.is_cancelled() {
            return;
        }
        let list_url = format!("{}lora/list", prepared.endpoint);
        let response =
            tokio::time::timeout(Duration::from_secs(5), self.client.get(list_url).send())
                .await
                .ok()
                .and_then(Result::ok);
        let Some(response) = response.filter(|response| response.status().is_success()) else {
            return;
        };
        let Ok(value) = response.json::<Value>().await else {
            return;
        };
        let Some(loras) = value.get("loras").and_then(Value::as_object) else {
            return;
        };
        if !prepared.lora_id.is_empty() && loras.contains_key(&prepared.lora_id) {
            payload
                .as_object_mut()
                .expect("payload is an object")
                .insert("lora_id".into(), Value::String(prepared.lora_id.clone()));
            return;
        }
        let unload_url = format!("{}lora/unload", prepared.endpoint);
        let _ =
            tokio::time::timeout(Duration::from_secs(5), self.client.post(unload_url).send()).await;
    }
}

pub fn prepare_tts_request(
    config: &TtsConfig,
    request: &TtsRequest,
) -> Result<PreparedTtsRequest, TtsError> {
    let text = clean_tts_text(&request.text);
    if text.is_empty() {
        return Err(TtsError::InvalidRequest("text cannot be empty".into()));
    }
    if text.len() > MAX_TTS_TEXT_BYTES {
        return Err(TtsError::InvalidRequest(format!(
            "text exceeds the {MAX_TTS_TEXT_BYTES} byte limit"
        )));
    }
    let reference_character = if config.reference_character.trim().is_empty() {
        request.character.trim()
    } else {
        config.reference_character.trim()
    };
    if !safe_reference_character(reference_character) {
        return Err(TtsError::InvalidRequest(
            "reference character is not a safe file name".into(),
        ));
    }
    let endpoint = normalize_api_url(&config.api_url)?;
    let reference_root = config.project_root.join("audio_reference");
    let reference_audio = reference_audio_path(&reference_root, reference_character);
    let (prompt_text, lora_id) = reference_metadata(
        &reference_root.join("dialog.json"),
        reference_character,
        &config.language,
    );
    let mut payload = Map::from_iter([
        (
            "refer_wav_path".into(),
            Value::String(reference_audio.to_string_lossy().into_owned()),
        ),
        ("text".into(), Value::String(text.clone())),
        (
            "text_language".into(),
            Value::String(config.language.clone()),
        ),
        ("cut_punc".into(), Value::String(String::new())),
        (
            "temperature".into(),
            json!(config.temperature.clamp(0.01, 2.0)),
        ),
    ]);
    if !prompt_text.is_empty() {
        payload.insert("prompt_text".into(), Value::String(prompt_text));
    }
    let speed = request.speed_factor.clamp(0.75, 1.25);
    if (speed - 1.0).abs() >= 0.015 {
        payload.insert(
            "speed_factor".into(),
            json!((speed * 1000.0).round() / 1000.0),
        );
    }
    Ok(PreparedTtsRequest {
        endpoint,
        payload: Value::Object(payload),
        prepared_text: text,
        language: config.language.clone(),
        lora_id,
    })
}

pub fn clean_tts_text(source: &str) -> String {
    let source = truncate_search_sources(source);
    let mut output = String::with_capacity(source.len());
    let mut remaining = source;
    while let Some(open) = remaining.find('[') {
        output.push_str(&remaining[..open]);
        let tail = &remaining[open + 1..];
        let Some(close) = tail.find(']') else {
            output.push_str(&remaining[open..]);
            remaining = "";
            break;
        };
        let tag = &tail[..close];
        if tag != "DONE"
            && (tag.is_empty()
                || !tag
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-')))
        {
            output.push_str(&remaining[open..open + close + 2]);
        }
        remaining = &tail[close + 1..];
    }
    output.push_str(remaining);
    output.trim().to_owned()
}

fn truncate_search_sources(source: &str) -> &str {
    ["web_search_sources", "search_sources", "sources"]
        .into_iter()
        .filter_map(|key| source.find(&format!("\"{key}\"")))
        .filter_map(|index| source[..index].rfind('{'))
        .min()
        .map(|index| &source[..index])
        .unwrap_or(source)
}

fn normalize_api_url(source: &str) -> Result<String, TtsError> {
    let source = source.trim();
    let source = if source.is_empty() {
        DEFAULT_TTS_URL
    } else {
        source
    };
    if source.len() > 2048 || !(source.starts_with("http://") || source.starts_with("https://")) {
        return Err(TtsError::InvalidRequest(
            "API URL must be an HTTP or HTTPS URL no longer than 2048 bytes".into(),
        ));
    }
    Ok(if source.ends_with('/') {
        source.to_owned()
    } else {
        format!("{source}/")
    })
}

fn safe_reference_character(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && !value.contains(['/', '\\', '\0'])
}

fn reference_audio_path(root: &Path, character: &str) -> PathBuf {
    REFERENCE_EXTENSIONS
        .iter()
        .map(|extension| root.join(format!("{character}.{extension}")))
        .find(|path| path.is_file())
        .unwrap_or_else(|| root.join(format!("{character}.mp3")))
}

fn reference_metadata(path: &Path, character: &str, language: &str) -> (String, String) {
    let Ok(metadata) = fs::metadata(path) else {
        return (String::new(), String::new());
    };
    if metadata.len() > MAX_DIALOG_JSON_BYTES {
        return (String::new(), String::new());
    }
    let Ok(source) = fs::read(path) else {
        return (String::new(), String::new());
    };
    let Ok(value) = serde_json::from_slice::<Value>(&source) else {
        return (String::new(), String::new());
    };
    let prompt = if matches!(language, "Japanese" | "ja" | "日文") {
        value
            .get(character)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned()
    } else {
        String::new()
    };
    let lora_id = value
        .get("__groups")
        .and_then(Value::as_object)
        .and_then(|groups| {
            groups.values().find_map(|group| {
                let object = group.as_object()?;
                let members = object.get("characters")?.as_array()?;
                members
                    .iter()
                    .any(|member| member.as_str() == Some(character))
                    .then(|| {
                        object
                            .get("lora_id")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .trim()
                            .to_owned()
                    })
            })
        })
        .unwrap_or_default();
    (prompt, lora_id)
}

fn configure_media_payload(payload: &mut Value, streaming: bool) {
    let payload = payload.as_object_mut().expect("payload is an object");
    payload.insert(
        "stream_mode".into(),
        Value::String(if streaming { "normal" } else { "close" }.into()),
    );
    payload.insert(
        "media_type".into(),
        Value::String(if streaming { "ogg" } else { "wav" }.into()),
    );
    if streaming {
        payload.insert("stream_format".into(), Value::String("framed".into()));
        payload.insert("chunk_size".into(), Value::from(8));
    } else {
        payload.remove("stream_format");
        payload.remove("chunk_size");
    }
}

fn streaming_failure_is_incompatible(status: StatusCode) -> bool {
    matches!(status.as_u16(), 400 | 404 | 405 | 406 | 415 | 422 | 501)
}

async fn consume_audio_response<F>(
    response: Response,
    streaming: bool,
    cancellation: &CancellationToken,
    on_audio: &mut F,
) -> Result<(usize, usize), TtsError>
where
    F: FnMut(TtsAudioChunk),
{
    let framed = streaming
        && response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .is_some_and(|value| {
                value
                    .to_ascii_lowercase()
                    .contains("application/octet-stream")
            });
    let media_type = if streaming { "ogg" } else { "wav" };
    let mut stream = response.bytes_stream();
    let mut total = 0usize;
    let mut count = 0usize;
    let mut decoder = FramedAudioDecoder::default();
    let mut unframed = Vec::new();
    while let Some(next) = tokio::select! {
        _ = cancellation.cancelled() => return Err(TtsError::Cancelled),
        next = stream.next() => next,
    } {
        let bytes = next.map_err(|_| TtsError::Http("audio stream failed"))?;
        total = total
            .checked_add(bytes.len())
            .ok_or(TtsError::AudioTooLarge)?;
        if total > MAX_AUDIO_BYTES {
            return Err(TtsError::AudioTooLarge);
        }
        if framed {
            for audio in decoder.push(&bytes)? {
                count += 1;
                on_audio(TtsAudioChunk {
                    bytes: audio,
                    media_type: media_type.into(),
                });
            }
        } else if streaming {
            if !bytes.is_empty() {
                count += 1;
                on_audio(TtsAudioChunk {
                    bytes: bytes.to_vec(),
                    media_type: media_type.into(),
                });
            }
        } else {
            unframed.extend_from_slice(&bytes);
        }
    }
    if framed {
        decoder.finish()?;
    } else if !streaming && !unframed.is_empty() {
        count = 1;
        on_audio(TtsAudioChunk {
            bytes: unframed,
            media_type: media_type.into(),
        });
    }
    if count == 0 {
        return Err(TtsError::Http("audio response was empty"));
    }
    Ok((count, total))
}

async fn read_error_body(
    response: Response,
    cancellation: &CancellationToken,
) -> Result<String, TtsError> {
    let mut stream = response.bytes_stream();
    let mut body = Vec::new();
    while let Some(next) = tokio::select! {
        _ = cancellation.cancelled() => return Err(TtsError::Cancelled),
        next = stream.next() => next,
    } {
        let bytes = next.map_err(|_| TtsError::Http("error response failed"))?;
        let remaining = MAX_ERROR_BODY_BYTES.saturating_sub(body.len());
        body.extend_from_slice(&bytes[..bytes.len().min(remaining)]);
        if body.len() >= MAX_ERROR_BODY_BYTES {
            break;
        }
    }
    let text = String::from_utf8_lossy(&body).trim().to_owned();
    Ok(if text.is_empty() {
        "request failed".into()
    } else {
        text
    })
}

#[derive(Default)]
struct FramedAudioDecoder {
    buffer: Vec<u8>,
    expected: Option<usize>,
}

impl FramedAudioDecoder {
    fn push(&mut self, bytes: &[u8]) -> Result<Vec<Vec<u8>>, TtsError> {
        self.buffer.extend_from_slice(bytes);
        let mut output = Vec::new();
        loop {
            if self.expected.is_none() {
                if self.buffer.len() < 4 {
                    break;
                }
                let size = u32::from_be_bytes(self.buffer[..4].try_into().unwrap()) as usize;
                self.buffer.drain(..4);
                if size == 0 || size > MAX_AUDIO_CHUNK_BYTES {
                    return Err(TtsError::InvalidFramedChunk);
                }
                self.expected = Some(size);
            }
            let expected = self.expected.expect("framed size is set");
            if self.buffer.len() < expected {
                break;
            }
            output.push(self.buffer.drain(..expected).collect());
            self.expected = None;
        }
        if self.buffer.len() > MAX_AUDIO_CHUNK_BYTES {
            return Err(TtsError::InvalidFramedChunk);
        }
        Ok(output)
    }

    fn finish(self) -> Result<(), TtsError> {
        if self.expected.is_some() || !self.buffer.is_empty() {
            Err(TtsError::IncompleteFramedStream)
        } else {
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;
    use std::time::Duration;

    fn config(root: &Path) -> TtsConfig {
        TtsConfig {
            api_url: "http://127.0.0.1:9880".into(),
            language: "Japanese".into(),
            reference_character: String::new(),
            streaming: true,
            temperature: 9.0,
            project_root: root.to_owned(),
        }
    }

    #[test]
    fn request_payload_matches_reference_prompt_lora_and_bounds() {
        let root = tempfile_dir();
        let references = root.join("audio_reference");
        fs::create_dir(&references).unwrap();
        fs::write(references.join("ran.wav"), b"wave").unwrap();
        fs::write(
            references.join("dialog.json"),
            br#"{"ran":"Japanese prompt","__groups":{"afterglow":{"characters":["ran"],"lora_id":"afterglow"}}}"#,
        )
        .unwrap();
        let prepared = prepare_tts_request(
            &config(&root),
            &TtsRequest {
                text: "hello [smile] world [DONE]".into(),
                character: "ran".into(),
                speed_factor: 3.0,
            },
        )
        .unwrap();
        assert_eq!(prepared.endpoint, "http://127.0.0.1:9880/");
        assert_eq!(prepared.prepared_text, "hello  world");
        assert_eq!(prepared.payload["temperature"], 2.0);
        assert_eq!(prepared.payload["speed_factor"], 1.25);
        assert_eq!(prepared.payload["prompt_text"], "Japanese prompt");
        assert!(
            prepared.payload["refer_wav_path"]
                .as_str()
                .unwrap()
                .ends_with("ran.wav")
        );
        assert_eq!(prepared.lora_id, "afterglow");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unsafe_reference_character_and_oversized_text_are_rejected() {
        let root = tempfile_dir();
        let unsafe_request = prepare_tts_request(
            &config(&root),
            &TtsRequest {
                text: "hello".into(),
                character: "../secret".into(),
                speed_factor: 1.0,
            },
        );
        assert!(matches!(unsafe_request, Err(TtsError::InvalidRequest(_))));
        let large_request = prepare_tts_request(
            &config(&root),
            &TtsRequest {
                text: "x".repeat(MAX_TTS_TEXT_BYTES + 1),
                character: "ran".into(),
                speed_factor: 1.0,
            },
        );
        assert!(matches!(large_request, Err(TtsError::InvalidRequest(_))));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn action_and_search_source_metadata_is_not_spoken() {
        assert_eq!(
            clean_tts_text("台词[happy]尾声 {\"web_search_sources\":[{\"title\":\"x\"}]}"),
            "台词尾声"
        );
        assert_eq!(
            clean_tts_text("keep [not a tag] text"),
            "keep [not a tag] text"
        );
    }

    #[test]
    fn framed_audio_decoder_handles_split_headers_and_multiple_chunks() {
        let mut decoder = FramedAudioDecoder::default();
        let mut encoded = Vec::new();
        for chunk in [b"one".as_slice(), b"second".as_slice()] {
            encoded.extend_from_slice(&(chunk.len() as u32).to_be_bytes());
            encoded.extend_from_slice(chunk);
        }
        assert!(decoder.push(&encoded[..2]).unwrap().is_empty());
        let output = decoder.push(&encoded[2..]).unwrap();
        assert_eq!(output, vec![b"one".to_vec(), b"second".to_vec()]);
        decoder.finish().unwrap();
    }

    #[test]
    fn framed_audio_decoder_rejects_invalid_or_incomplete_chunks() {
        let mut invalid = FramedAudioDecoder::default();
        assert!(matches!(
            invalid.push(&0u32.to_be_bytes()),
            Err(TtsError::InvalidFramedChunk)
        ));
        let mut incomplete = FramedAudioDecoder::default();
        incomplete.push(&4u32.to_be_bytes()).unwrap();
        assert!(matches!(
            incomplete.finish(),
            Err(TtsError::IncompleteFramedStream)
        ));
    }

    #[tokio::test]
    async fn incompatible_streaming_endpoint_retries_once_with_wav() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let mut modes = Vec::new();
            for request_index in 0..3 {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let (headers, body) = read_http_request(&mut stream);
                if request_index == 0 {
                    assert!(headers.starts_with("GET /lora/list "));
                    write_http_response(&mut stream, "404 Not Found", "text/plain", b"missing");
                    continue;
                }
                assert!(headers.starts_with("POST / "));
                let payload: Value = serde_json::from_slice(&body).unwrap();
                modes.push(
                    payload
                        .get("stream_mode")
                        .and_then(Value::as_str)
                        .unwrap()
                        .to_owned(),
                );
                if request_index == 1 {
                    write_http_response(
                        &mut stream,
                        "415 Unsupported Media Type",
                        "text/plain",
                        b"streaming unsupported",
                    );
                } else {
                    write_http_response(&mut stream, "200 OK", "audio/wav", b"RIFF-native-wav");
                }
            }
            modes
        });

        let root = tempfile_dir();
        let transport = TtsTransport::new(TtsConfig {
            api_url: format!("http://{address}"),
            language: "Chinese".into(),
            reference_character: String::new(),
            streaming: true,
            temperature: 0.9,
            project_root: root.clone(),
        })
        .unwrap();
        let mut chunks = Vec::new();
        let outcome = transport
            .synthesize(
                &TtsRequest {
                    text: "你好".into(),
                    character: "ran".into(),
                    speed_factor: 1.0,
                },
                &CancellationToken::new(),
                |chunk| chunks.push(chunk),
            )
            .await
            .unwrap();

        assert_eq!(server.join().unwrap(), ["normal", "close"]);
        assert!(!outcome.used_streaming);
        assert_eq!(outcome.chunk_count, 1);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].media_type, "wav");
        assert_eq!(chunks[0].bytes, b"RIFF-native-wav");
        fs::remove_dir_all(root).unwrap();
    }

    fn read_http_request(stream: &mut TcpStream) -> (String, Vec<u8>) {
        let mut request = Vec::new();
        let header_end = loop {
            if let Some(index) = request.windows(4).position(|window| window == b"\r\n\r\n") {
                break index + 4;
            }
            let mut buffer = [0u8; 4096];
            let read = stream.read(&mut buffer).unwrap();
            assert!(read > 0, "HTTP request ended before its headers");
            request.extend_from_slice(&buffer[..read]);
        };
        let headers = String::from_utf8(request[..header_end].to_vec()).unwrap();
        let content_length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().unwrap())
            })
            .unwrap_or(0);
        while request.len() - header_end < content_length {
            let mut buffer = [0u8; 4096];
            let read = stream.read(&mut buffer).unwrap();
            assert!(read > 0, "HTTP request ended before its body");
            request.extend_from_slice(&buffer[..read]);
        }
        let body = request[header_end..header_end + content_length].to_vec();
        (headers, body)
    }

    fn write_http_response(stream: &mut TcpStream, status: &str, content_type: &str, body: &[u8]) {
        let headers = format!(
            "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        stream.write_all(headers.as_bytes()).unwrap();
        stream.write_all(body).unwrap();
        stream.flush().unwrap();
    }

    fn tempfile_dir() -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "bandori-tts-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&path).unwrap();
        path
    }
}
