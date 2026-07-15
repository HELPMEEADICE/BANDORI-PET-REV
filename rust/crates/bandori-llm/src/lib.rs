use bandori_llm_protocol::{
    LlmApiMode, LlmProtocolError, LlmSseDecoder, LlmStreamEvent, TokenUsage,
    build_chat_completions_body, build_responses_body, chat_completions_api_url, responses_api_url,
    supports_openai_responses_api,
};
use futures_util::StreamExt;
use reqwest::header::{ACCEPT, AUTHORIZATION, CONTENT_TYPE, HeaderMap, HeaderValue, USER_AGENT};
use serde_json::Value;
use std::fmt;
use std::time::Duration;
use thiserror::Error;
use tokio_util::sync::CancellationToken;

const OPENAI_COMPAT_USER_AGENT: &str = concat!(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ",
    "AppleWebKit/537.36 (KHTML, like Gecko) ",
    "Chrome/120.0.0.0 Safari/537.36"
);
const MAX_SSE_LINE_BYTES: usize = 2 * 1024 * 1024;
const MAX_ERROR_BODY_BYTES: usize = 64 * 1024;

#[derive(Clone)]
pub struct LlmTransportConfig {
    pub api_url: String,
    pub api_key: String,
    pub model: String,
    pub mode: LlmApiMode,
    pub enable_thinking: Option<bool>,
}

impl fmt::Debug for LlmTransportConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LlmTransportConfig")
            .field("api_url", &redacted_url(&self.api_url))
            .field(
                "api_key",
                &if self.api_key.is_empty() {
                    ""
                } else {
                    "<redacted>"
                },
            )
            .field("model", &self.model)
            .field("mode", &self.mode)
            .field("enable_thinking", &self.enable_thinking)
            .finish()
    }
}

#[derive(Clone, Debug, Default)]
pub struct LlmTransportRequest {
    pub messages: Vec<Value>,
    pub tools: Vec<Value>,
    pub previous_response_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LlmStreamOutcome {
    pub mode: LlmApiMode,
    pub response_id: String,
    pub usage: Option<TokenUsage>,
}

#[derive(Debug, Error)]
pub enum LlmTransportError {
    #[error("LLM request was cancelled")]
    Cancelled,
    #[error("LLM transport failed: {0}")]
    Http(&'static str),
    #[error(transparent)]
    Protocol(#[from] LlmProtocolError),
    #[error("LLM endpoint returned HTTP {status}: {message}")]
    HttpStatus { status: u16, message: String },
    #[error("LLM stream ended without a completion marker")]
    IncompleteStream,
    #[error("LLM stream contained a line larger than {MAX_SSE_LINE_BYTES} bytes")]
    SseLineTooLong,
    #[error("invalid authorization header")]
    InvalidAuthorizationHeader,
}

#[derive(Clone, Debug)]
pub struct LlmTransport {
    client: reqwest::Client,
    config: LlmTransportConfig,
}

impl LlmTransport {
    pub fn new(config: LlmTransportConfig) -> Result<Self, LlmTransportError> {
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(15))
            .timeout(Duration::from_secs(180))
            .build()
            .map_err(sanitized_http_error)?;
        Ok(Self { client, config })
    }

    pub fn effective_mode(&self) -> LlmApiMode {
        if self.config.mode == LlmApiMode::Responses
            && supports_openai_responses_api(&self.config.api_url)
        {
            LlmApiMode::Responses
        } else {
            LlmApiMode::ChatCompletions
        }
    }

    pub async fn stream<F>(
        &self,
        request: &LlmTransportRequest,
        cancellation: &CancellationToken,
        mut on_event: F,
    ) -> Result<LlmStreamOutcome, LlmTransportError>
    where
        F: FnMut(LlmStreamEvent),
    {
        if cancellation.is_cancelled() {
            return Err(LlmTransportError::Cancelled);
        }
        let mode = self.effective_mode();
        let endpoint = match mode {
            LlmApiMode::ChatCompletions => chat_completions_api_url(&self.config.api_url),
            LlmApiMode::Responses => responses_api_url(&self.config.api_url),
        };
        let body = match mode {
            LlmApiMode::ChatCompletions => build_chat_completions_body(
                &endpoint,
                &self.config.model,
                &request.messages,
                true,
                self.config.enable_thinking,
                &request.tools,
            ),
            LlmApiMode::Responses => build_responses_body(
                &self.config.model,
                &request.messages,
                true,
                self.config.enable_thinking,
                &request.tools,
                &request.previous_response_id,
            ),
        };
        let response = tokio::select! {
            _ = cancellation.cancelled() => return Err(LlmTransportError::Cancelled),
            response = self.client
                .post(endpoint)
                .headers(self.headers()?)
                .json(&body)
                .send() => response.map_err(sanitized_http_error)?,
        };
        if !response.status().is_success() {
            let status = response.status().as_u16();
            let body = read_error_body(response, cancellation).await?;
            return Err(LlmTransportError::HttpStatus {
                status,
                message: error_message(&body),
            });
        }

        let mut decoder = LlmSseDecoder::new(mode);
        let mut lines = SseLineBuffer::default();
        let mut response_id = String::new();
        let mut usage = None;
        let stream = response.bytes_stream();
        tokio::pin!(stream);
        loop {
            let chunk = tokio::select! {
                _ = cancellation.cancelled() => return Err(LlmTransportError::Cancelled),
                chunk = stream.next() => chunk,
            };
            let Some(chunk) = chunk else {
                break;
            };
            let chunk = chunk.map_err(sanitized_http_error)?;
            for line in lines.push(&chunk)? {
                emit_decoded_events(
                    &mut decoder,
                    &line,
                    &mut response_id,
                    &mut usage,
                    &mut on_event,
                )?;
            }
        }
        if let Some(line) = lines.finish()? {
            emit_decoded_events(
                &mut decoder,
                &line,
                &mut response_id,
                &mut usage,
                &mut on_event,
            )?;
        }
        if !decoder.is_completed() {
            return Err(LlmTransportError::IncompleteStream);
        }
        Ok(LlmStreamOutcome {
            mode,
            response_id,
            usage,
        })
    }

    fn headers(&self) -> Result<HeaderMap, LlmTransportError> {
        let mut headers = HeaderMap::new();
        headers.insert(
            USER_AGENT,
            HeaderValue::from_static(OPENAI_COMPAT_USER_AGENT),
        );
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers.insert(ACCEPT, HeaderValue::from_static("text/event-stream"));
        if !self.config.api_key.is_empty() {
            let mut value = HeaderValue::from_str(&format!("Bearer {}", self.config.api_key))
                .map_err(|_| LlmTransportError::InvalidAuthorizationHeader)?;
            value.set_sensitive(true);
            headers.insert(AUTHORIZATION, value);
        }
        Ok(headers)
    }
}

fn redacted_url(url: &str) -> String {
    let query = url.find('?');
    let fragment = url.find('#');
    let boundary = match (query, fragment) {
        (Some(left), Some(right)) => Some(left.min(right)),
        (Some(position), None) | (None, Some(position)) => Some(position),
        (None, None) => None,
    };
    boundary
        .map(|position| format!("{}?<redacted>", &url[..position]))
        .unwrap_or_else(|| url.to_owned())
}

fn sanitized_http_error(error: reqwest::Error) -> LlmTransportError {
    let kind = if error.is_timeout() {
        "request timed out"
    } else if error.is_connect() {
        "connection failed"
    } else if error.is_decode() {
        "response decoding failed"
    } else if error.is_body() {
        "response body failed"
    } else {
        "request failed"
    };
    LlmTransportError::Http(kind)
}

async fn read_error_body(
    response: reqwest::Response,
    cancellation: &CancellationToken,
) -> Result<Vec<u8>, LlmTransportError> {
    let stream = response.bytes_stream();
    tokio::pin!(stream);
    let mut body = Vec::new();
    while body.len() < MAX_ERROR_BODY_BYTES {
        let chunk = tokio::select! {
            _ = cancellation.cancelled() => return Err(LlmTransportError::Cancelled),
            chunk = stream.next() => chunk,
        };
        let Some(chunk) = chunk else {
            break;
        };
        let chunk = chunk.map_err(sanitized_http_error)?;
        let remaining = MAX_ERROR_BODY_BYTES - body.len();
        body.extend_from_slice(&chunk[..chunk.len().min(remaining)]);
    }
    Ok(body)
}

fn emit_decoded_events<F>(
    decoder: &mut LlmSseDecoder,
    line: &str,
    response_id: &mut String,
    usage: &mut Option<TokenUsage>,
    on_event: &mut F,
) -> Result<(), LlmTransportError>
where
    F: FnMut(LlmStreamEvent),
{
    for event in decoder.feed_line(line)? {
        match &event {
            LlmStreamEvent::ResponseId { id } => response_id.clone_from(id),
            LlmStreamEvent::Usage { usage: value } => *usage = Some(value.clone()),
            _ => {}
        }
        on_event(event);
    }
    Ok(())
}

#[derive(Default)]
struct SseLineBuffer {
    bytes: Vec<u8>,
}

impl SseLineBuffer {
    fn push(&mut self, chunk: &[u8]) -> Result<Vec<String>, LlmTransportError> {
        self.bytes.extend_from_slice(chunk);
        let mut lines = Vec::new();
        while let Some(position) = self.bytes.iter().position(|byte| *byte == b'\n') {
            if position > MAX_SSE_LINE_BYTES {
                return Err(LlmTransportError::SseLineTooLong);
            }
            let line = self.bytes.drain(..=position).collect::<Vec<_>>();
            lines.push(String::from_utf8_lossy(&line[..line.len() - 1]).into_owned());
        }
        if self.bytes.len() > MAX_SSE_LINE_BYTES {
            return Err(LlmTransportError::SseLineTooLong);
        }
        Ok(lines)
    }

    fn finish(&mut self) -> Result<Option<String>, LlmTransportError> {
        if self.bytes.len() > MAX_SSE_LINE_BYTES {
            return Err(LlmTransportError::SseLineTooLong);
        }
        Ok((!self.bytes.is_empty())
            .then(|| String::from_utf8_lossy(&std::mem::take(&mut self.bytes)).into_owned()))
    }
}

fn error_message(body: &[u8]) -> String {
    let text = String::from_utf8_lossy(body).trim().to_owned();
    serde_json::from_slice::<Value>(body)
        .ok()
        .and_then(|value| {
            value
                .get("error")
                .and_then(|error| error.get("message"))
                .or_else(|| value.get("message"))
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .filter(|message| !message.is_empty())
        .unwrap_or_else(|| {
            if text.is_empty() {
                "request failed".to_owned()
            } else {
                text
            }
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::{Arc, Mutex};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::{TcpListener, TcpStream};

    fn config(api_url: String, mode: LlmApiMode) -> LlmTransportConfig {
        LlmTransportConfig {
            api_url,
            api_key: "super-secret".to_owned(),
            model: "fixture-model".to_owned(),
            mode,
            enable_thinking: Some(true),
        }
    }

    async fn read_request(socket: &mut TcpStream) -> Vec<u8> {
        let mut request = Vec::new();
        let mut buffer = [0_u8; 2048];
        let header_end = loop {
            let read = socket.read(&mut buffer).await.unwrap();
            assert!(read > 0, "client closed before sending HTTP headers");
            request.extend_from_slice(&buffer[..read]);
            if let Some(position) = request.windows(4).position(|window| window == b"\r\n\r\n") {
                break position + 4;
            }
        };
        let headers = String::from_utf8_lossy(&request[..header_end]);
        let content_length = headers
            .lines()
            .find_map(|line| {
                line.to_ascii_lowercase()
                    .strip_prefix("content-length:")
                    .map(str::trim)
                    .map(str::to_owned)
            })
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or_default();
        while request.len() < header_end + content_length {
            let read = socket.read(&mut buffer).await.unwrap();
            assert!(read > 0, "client closed before sending HTTP body");
            request.extend_from_slice(&buffer[..read]);
        }
        request
    }

    async fn write_chunk(socket: &mut TcpStream, bytes: &[u8]) {
        socket
            .write_all(format!("{:x}\r\n", bytes.len()).as_bytes())
            .await
            .unwrap();
        socket.write_all(bytes).await.unwrap();
        socket.write_all(b"\r\n").await.unwrap();
    }

    #[test]
    fn debug_output_redacts_api_keys_and_responses_fall_back_for_compatible_providers() {
        let transport = LlmTransport::new(config(
            "https://openrouter.ai/api/v1/responses?key=super-secret#token".to_owned(),
            LlmApiMode::Responses,
        ))
        .unwrap();
        assert_eq!(transport.effective_mode(), LlmApiMode::ChatCompletions);
        let debug = format!("{:?}", transport.config);
        assert!(debug.contains("<redacted>"));
        assert!(!debug.contains("super-secret"));
        assert!(!debug.contains("token"));
    }

    #[tokio::test]
    async fn transport_streams_split_utf8_sse_and_sends_redacted_openai_request() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let request = read_request(&mut socket).await;
            socket
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n",
                )
                .await
                .unwrap();
            let payload =
                "data: {\"choices\":[{\"delta\":{\"content\":\"你好\"},\"finish_reason\":null}]}\n";
            let bytes = payload.as_bytes();
            let split = bytes.iter().position(|byte| *byte >= 0x80).unwrap() + 1;
            write_chunk(&mut socket, &bytes[..split]).await;
            write_chunk(&mut socket, &bytes[split..]).await;
            write_chunk(&mut socket, b"data: [DONE]\n").await;
            socket.write_all(b"0\r\n\r\n").await.unwrap();
            request
        });

        let transport = LlmTransport::new(config(
            format!("http://{address}/v1/chat/completions"),
            LlmApiMode::ChatCompletions,
        ))
        .unwrap();
        let events = Arc::new(Mutex::new(Vec::new()));
        let captured = Arc::clone(&events);
        let outcome = transport
            .stream(
                &LlmTransportRequest {
                    messages: vec![json!({"role": "user", "content": "hello"})],
                    ..Default::default()
                },
                &CancellationToken::new(),
                move |event| captured.lock().unwrap().push(event),
            )
            .await
            .unwrap();
        assert_eq!(outcome.mode, LlmApiMode::ChatCompletions);
        assert_eq!(
            events.lock().unwrap().as_slice(),
            [
                LlmStreamEvent::TextDelta {
                    text: "你好".to_owned()
                },
                LlmStreamEvent::Completed,
            ]
        );
        let request = String::from_utf8_lossy(&server.await.unwrap()).into_owned();
        assert!(request.contains("authorization: Bearer super-secret"));
        assert!(request.contains("\"model\":\"fixture-model\""));
    }

    #[tokio::test]
    async fn cancellation_interrupts_an_open_stream() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let _request = read_request(&mut socket).await;
            socket
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n",
                )
                .await
                .unwrap();
            tokio::time::sleep(Duration::from_secs(5)).await;
        });
        let transport = LlmTransport::new(config(
            format!("http://{address}/v1/chat/completions"),
            LlmApiMode::ChatCompletions,
        ))
        .unwrap();
        let cancellation = CancellationToken::new();
        let child = cancellation.clone();
        let request = LlmTransportRequest::default();
        let task = tokio::spawn(async move { transport.stream(&request, &child, |_| {}).await });
        tokio::time::sleep(Duration::from_millis(50)).await;
        cancellation.cancel();
        let result = tokio::time::timeout(Duration::from_secs(1), task)
            .await
            .expect("cancelled stream should stop promptly")
            .unwrap();
        assert!(matches!(result, Err(LlmTransportError::Cancelled)));
        server.abort();
    }

    #[tokio::test]
    async fn structured_http_errors_are_reported_without_unbounded_buffering() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let _request = read_request(&mut socket).await;
            let body = br#"{"error":{"message":"bad key"}}"#;
            socket
                .write_all(
                    format!(
                        "HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        body.len()
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
            socket.write_all(body).await.unwrap();
        });
        let transport = LlmTransport::new(config(
            format!("http://{address}/v1/chat/completions"),
            LlmApiMode::ChatCompletions,
        ))
        .unwrap();
        let result = transport
            .stream(
                &LlmTransportRequest::default(),
                &CancellationToken::new(),
                |_| {},
            )
            .await;
        assert!(matches!(
            result,
            Err(LlmTransportError::HttpStatus {
                status: 401,
                ref message,
            }) if message == "bad key"
        ));
        server.await.unwrap();
    }

    #[test]
    fn provider_error_messages_are_bounded_and_structured() {
        assert_eq!(
            error_message(br#"{"error":{"message":"bad key"}}"#),
            "bad key"
        );
        assert_eq!(error_message(b""), "request failed");
    }
}
