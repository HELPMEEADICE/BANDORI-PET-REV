use futures_util::StreamExt;
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE, HeaderMap, HeaderValue};
use reqwest::{Client, Url};
use serde_json::Value;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use thiserror::Error;
use tokio_util::sync::CancellationToken;

const DEFAULT_ASR_URL: &str = "http://127.0.0.1:8000/v1/audio/transcriptions";
const MAX_ASR_URL_BYTES: usize = 2048;
const MAX_AUDIO_BYTES: usize = 64 * 1024 * 1024;
const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_ERROR_BYTES: usize = 64 * 1024;
const MAX_MODEL_BYTES: usize = 256;
const MAX_LANGUAGE_BYTES: usize = 32;
static NEXT_BOUNDARY: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, PartialEq)]
pub struct AsrConfig {
    pub api_url: String,
    pub api_key: String,
    pub model_id: String,
    pub language: String,
    pub timeout_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedAsrRequest {
    pub endpoint: String,
    pub content_type: String,
    pub body: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AsrOutcome {
    pub text: String,
}

#[derive(Debug, Error)]
pub enum AsrError {
    #[error("ASR request was cancelled")]
    Cancelled,
    #[error("invalid ASR request: {0}")]
    InvalidRequest(String),
    #[error("ASR audio exceeded the {MAX_AUDIO_BYTES} byte limit")]
    AudioTooLarge,
    #[error("ASR response exceeded the {MAX_RESPONSE_BYTES} byte limit")]
    ResponseTooLarge,
    #[error("ASR transport failed: {0}")]
    Http(&'static str),
    #[error("ASR endpoint returned HTTP {status}: {message}")]
    HttpStatus { status: u16, message: String },
    #[error("ASR endpoint returned invalid JSON")]
    InvalidJson,
    #[error("ASR endpoint returned no usable text")]
    EmptyTranscript,
}

#[derive(Clone, Debug)]
pub struct AsrTransport {
    client: Client,
    config: AsrConfig,
}

impl AsrTransport {
    pub fn new(config: AsrConfig) -> Result<Self, AsrError> {
        validate_config(&config)?;
        let timeout = Duration::from_secs(config.timeout_seconds.clamp(5, 300));
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(15))
            .timeout(timeout)
            .build()
            .map_err(|_| AsrError::Http("could not create HTTP client"))?;
        Ok(Self { client, config })
    }

    pub async fn transcribe(
        &self,
        audio: &[u8],
        media_type: &str,
        cancellation: &CancellationToken,
    ) -> Result<AsrOutcome, AsrError> {
        let prepared = prepare_asr_request(&self.config, audio, media_type)?;
        let mut headers = HeaderMap::new();
        headers.insert(
            CONTENT_TYPE,
            HeaderValue::from_str(&prepared.content_type)
                .map_err(|_| AsrError::InvalidRequest("invalid multipart content type".into()))?,
        );
        if !self.config.api_key.trim().is_empty() {
            let authorization = format!("Bearer {}", self.config.api_key.trim());
            headers.insert(
                AUTHORIZATION,
                HeaderValue::from_str(&authorization)
                    .map_err(|_| AsrError::InvalidRequest("invalid API key".into()))?,
            );
        }
        let response = tokio::select! {
            _ = cancellation.cancelled() => return Err(AsrError::Cancelled),
            response = self.client
                .post(&prepared.endpoint)
                .headers(headers)
                .body(prepared.body)
                .send() => response.map_err(|_| AsrError::Http("request failed"))?,
        };
        let status = response.status();
        let limit = if status.is_success() {
            MAX_RESPONSE_BYTES
        } else {
            MAX_ERROR_BYTES
        };
        let body = read_bounded_response(response, limit, cancellation).await?;
        if !status.is_success() {
            return Err(AsrError::HttpStatus {
                status: status.as_u16(),
                message: response_error_message(&body),
            });
        }
        let payload = serde_json::from_slice::<Value>(&body).map_err(|_| AsrError::InvalidJson)?;
        let text = transcript_from_payload(&payload).ok_or(AsrError::EmptyTranscript)?;
        Ok(AsrOutcome { text })
    }
}

pub fn prepare_asr_request(
    config: &AsrConfig,
    audio: &[u8],
    media_type: &str,
) -> Result<PreparedAsrRequest, AsrError> {
    validate_config(config)?;
    if audio.is_empty() {
        return Err(AsrError::InvalidRequest("audio cannot be empty".into()));
    }
    if audio.len() > MAX_AUDIO_BYTES {
        return Err(AsrError::AudioTooLarge);
    }
    let media_type = normalized_media_type(media_type)?;
    let endpoint = normalize_asr_api_url(&config.api_url)?;
    let boundary = format!(
        "bandori-asr-{}-{}",
        std::process::id(),
        NEXT_BOUNDARY.fetch_add(1, Ordering::Relaxed)
    );
    let body = build_multipart_body(
        &boundary,
        &config.model_id,
        &config.language,
        audio,
        media_type,
    );
    Ok(PreparedAsrRequest {
        endpoint,
        content_type: format!("multipart/form-data; boundary={boundary}"),
        body,
    })
}

pub fn normalize_asr_api_url(source: &str) -> Result<String, AsrError> {
    let source = source.trim();
    let source = if source.is_empty() {
        DEFAULT_ASR_URL.to_owned()
    } else if source.contains("://") {
        source.to_owned()
    } else {
        format!("http://{source}")
    };
    if source.len() > MAX_ASR_URL_BYTES || source.chars().any(char::is_control) {
        return Err(AsrError::InvalidRequest("invalid API URL".into()));
    }
    let mut url =
        Url::parse(&source).map_err(|_| AsrError::InvalidRequest("invalid API URL".into()))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err(AsrError::InvalidRequest(
            "API URL must use HTTP or HTTPS".into(),
        ));
    }
    let path = url.path().to_owned();
    let normalized = path.trim_end_matches('/').to_ascii_lowercase();
    if path.is_empty() || path == "/" || matches!(normalized.as_str(), "/v1" | "/v1/audio") {
        url.set_path("/v1/audio/transcriptions");
    } else if path.ends_with('/') {
        url.set_path(&format!("{path}v1/audio/transcriptions"));
    }
    Ok(url.into())
}

fn validate_config(config: &AsrConfig) -> Result<(), AsrError> {
    normalize_asr_api_url(&config.api_url)?;
    validate_text_field(&config.model_id, MAX_MODEL_BYTES, "model")?;
    if config.model_id.trim().is_empty() {
        return Err(AsrError::InvalidRequest("model cannot be empty".into()));
    }
    validate_text_field(&config.language, MAX_LANGUAGE_BYTES, "language")?;
    if !config.api_key.is_empty()
        && (config.api_key.len() > 16 * 1024 || config.api_key.chars().any(char::is_control))
    {
        return Err(AsrError::InvalidRequest("invalid API key".into()));
    }
    Ok(())
}

fn validate_text_field(value: &str, maximum: usize, label: &str) -> Result<(), AsrError> {
    if value.len() > maximum || value.contains(['\r', '\n', '\0']) {
        Err(AsrError::InvalidRequest(format!("invalid {label}")))
    } else {
        Ok(())
    }
}

fn normalized_media_type(source: &str) -> Result<&'static str, AsrError> {
    match source.trim().to_ascii_lowercase().as_str() {
        "audio/wav" | "audio/x-wav" | "" => Ok("audio/wav"),
        "audio/mpeg" => Ok("audio/mpeg"),
        "audio/mp4" => Ok("audio/mp4"),
        "audio/ogg" => Ok("audio/ogg"),
        "audio/webm" => Ok("audio/webm"),
        _ => Err(AsrError::InvalidRequest(
            "unsupported audio media type".into(),
        )),
    }
}

fn build_multipart_body(
    boundary: &str,
    model: &str,
    language: &str,
    audio: &[u8],
    media_type: &str,
) -> Vec<u8> {
    let extension = match media_type {
        "audio/mpeg" => "mp3",
        "audio/mp4" => "m4a",
        "audio/ogg" => "ogg",
        "audio/webm" => "webm",
        _ => "wav",
    };
    let mut body = Vec::with_capacity(audio.len().saturating_add(1024));
    append_text_part(&mut body, boundary, "model", model.trim());
    if !language.trim().is_empty() {
        append_text_part(&mut body, boundary, "language", language.trim());
    }
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(
        format!(
            "Content-Disposition: form-data; name=\"file\"; filename=\"speech.{extension}\"\r\nContent-Type: {media_type}\r\n\r\n"
        )
        .as_bytes(),
    );
    body.extend_from_slice(audio);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    body
}

fn append_text_part(body: &mut Vec<u8>, boundary: &str, name: &str, value: &str) {
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(
        format!("Content-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").as_bytes(),
    );
}

async fn read_bounded_response(
    response: reqwest::Response,
    limit: usize,
    cancellation: &CancellationToken,
) -> Result<Vec<u8>, AsrError> {
    let mut stream = response.bytes_stream();
    let mut body = Vec::new();
    while let Some(next) = tokio::select! {
        _ = cancellation.cancelled() => return Err(AsrError::Cancelled),
        next = stream.next() => next,
    } {
        let bytes = next.map_err(|_| AsrError::Http("response stream failed"))?;
        if body.len().saturating_add(bytes.len()) > limit {
            return Err(AsrError::ResponseTooLarge);
        }
        body.extend_from_slice(&bytes);
    }
    Ok(body)
}

fn transcript_from_payload(payload: &Value) -> Option<String> {
    for key in ["text", "transcript", "result"] {
        if let Some(text) = payload.get(key).and_then(Value::as_str) {
            let text = text.trim();
            if !text.is_empty() {
                return Some(text.to_owned());
            }
        }
    }
    let text = payload
        .get("segments")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|segment| segment.get("text").and_then(Value::as_str))
        .collect::<String>();
    let text = text.trim();
    (!text.is_empty()).then(|| text.to_owned())
}

fn response_error_message(body: &[u8]) -> String {
    if let Ok(payload) = serde_json::from_slice::<Value>(body) {
        if let Some(message) = payload
            .get("error")
            .and_then(|error| {
                error
                    .as_str()
                    .or_else(|| error.get("message").and_then(Value::as_str))
                    .or_else(|| error.get("detail").and_then(Value::as_str))
            })
            .or_else(|| payload.get("detail").and_then(Value::as_str))
        {
            return message.trim().to_owned();
        }
    }
    let text = String::from_utf8_lossy(body).trim().to_owned();
    if text.is_empty() {
        "request failed".into()
    } else {
        text
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;
    use std::time::Duration;

    fn config(url: String) -> AsrConfig {
        AsrConfig {
            api_url: url,
            api_key: "secret-token".into(),
            model_id: "whisper-large-v3".into(),
            language: "zh".into(),
            timeout_seconds: 30,
        }
    }

    #[test]
    fn endpoint_normalization_matches_openai_compatible_routes() {
        assert_eq!(
            normalize_asr_api_url("127.0.0.1:8000").unwrap(),
            DEFAULT_ASR_URL
        );
        assert_eq!(
            normalize_asr_api_url("https://example.com/v1").unwrap(),
            "https://example.com/v1/audio/transcriptions"
        );
        assert!(normalize_asr_api_url("file:///tmp/asr").is_err());
    }

    #[test]
    fn multipart_body_contains_bounded_fields_and_binary_audio() {
        let prepared = prepare_asr_request(
            &config("http://localhost:8000".into()),
            b"RIFF-audio",
            "audio/wav",
        )
        .unwrap();
        assert!(
            prepared
                .content_type
                .starts_with("multipart/form-data; boundary=")
        );
        assert!(
            prepared
                .body
                .windows(16)
                .any(|part| part == b"whisper-large-v3")
        );
        assert!(prepared.body.windows(10).any(|part| part == b"RIFF-audio"));
        assert!(!String::from_utf8_lossy(&prepared.body).contains("secret-token"));
        assert!(matches!(
            prepare_asr_request(&config("http://localhost".into()), &[], "audio/wav"),
            Err(AsrError::InvalidRequest(_))
        ));
    }

    #[test]
    fn transcript_parser_accepts_compatible_shapes() {
        assert_eq!(
            transcript_from_payload(&serde_json::json!({"transcript":" hello "})).unwrap(),
            "hello"
        );
        assert_eq!(
            transcript_from_payload(&serde_json::json!({"segments":[{"text":"你"},{"text":"好"}]}))
                .unwrap(),
            "你好"
        );
        assert!(transcript_from_payload(&serde_json::json!({"text":""})).is_none());
    }

    #[tokio::test]
    async fn transport_posts_authorized_multipart_and_parses_segments() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let (headers, body) = read_http_request(&mut stream);
            assert!(headers.starts_with("POST /v1/audio/transcriptions "));
            assert!(
                headers
                    .to_ascii_lowercase()
                    .contains("authorization: bearer secret-token")
            );
            assert!(
                headers
                    .to_ascii_lowercase()
                    .contains("multipart/form-data; boundary=")
            );
            assert!(body.windows(11).any(|part| part == b"native-wave"));
            write_http_response(
                &mut stream,
                "200 OK",
                "application/json",
                r#"{"segments":[{"text":"语音"},{"text":"输入"}]}"#.as_bytes(),
            );
        });
        let transport = AsrTransport::new(config(format!("http://{address}"))).unwrap();
        let result = transport
            .transcribe(b"native-wave", "audio/wav", &CancellationToken::new())
            .await
            .unwrap();
        server.join().unwrap();
        assert_eq!(result.text, "语音输入");
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
}
