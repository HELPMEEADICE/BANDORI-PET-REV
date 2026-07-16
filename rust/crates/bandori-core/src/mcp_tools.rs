use crate::config::ConfigDocument;
use bandori_llm_protocol::LlmApiMode;
use reqwest::header::{ACCEPT, AUTHORIZATION, CONTENT_LENGTH, CONTENT_TYPE, HeaderValue};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio_util::sync::CancellationToken;
use url::Url;

const MCP_PROTOCOL_VERSION: &str = "2025-06-18";
const MCP_TOOL_PREFIX: &str = "mcp__";
const MAX_MCP_SERVERS: usize = 32;
const MAX_MCP_TOOLS_PER_SERVER: usize = 128;
const MAX_MCP_TOOLS_TOTAL: usize = 256;
const MAX_MCP_MESSAGE_BYTES: usize = 4 * 1024 * 1024;
const MAX_MCP_RESULT_CHARS: usize = 128 * 1024;
const MAX_LABEL_BYTES: usize = 80;
const MAX_DESCRIPTION_BYTES: usize = 4096;
const MAX_COMMAND_BYTES: usize = 4096;
const MAX_ARGUMENT_BYTES: usize = 16 * 1024;
const MAX_ENV_ENTRIES: usize = 64;
const MAX_ENV_KEY_BYTES: usize = 256;
const MAX_ENV_VALUE_BYTES: usize = 16 * 1024;
const MAX_AUTHORIZATION_BYTES: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum McpTransport {
    Stdio,
    Http,
    Native,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct McpServerConfig {
    enabled: bool,
    label: String,
    description: String,
    transport: McpTransport,
    command: String,
    args: Vec<String>,
    cwd: String,
    url: String,
    connector_id: String,
    authorization: String,
    allowed_tools: Vec<String>,
    require_approval: String,
    timeout_seconds: u64,
    env: BTreeMap<String, String>,
}

impl McpServerConfig {
    fn from_value(value: &Value) -> Result<Self, String> {
        let object = value
            .as_object()
            .ok_or_else(|| "MCP server entry must be an object".to_owned())?;
        let label = bounded_text(
            object
                .get("label")
                .or_else(|| object.get("server_label"))
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_LABEL_BYTES,
            "MCP server label",
            false,
        )?;
        if label.is_empty() {
            return Err("MCP server label cannot be empty".to_owned());
        }
        let transport = match object
            .get("transport")
            .and_then(Value::as_str)
            .unwrap_or("stdio")
            .trim()
            .to_ascii_lowercase()
            .as_str()
        {
            "http" => McpTransport::Http,
            "native" => McpTransport::Native,
            _ => McpTransport::Stdio,
        };
        let description = bounded_text(
            object
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_DESCRIPTION_BYTES,
            "MCP server description",
            true,
        )?;
        let command = bounded_text(
            object
                .get("command")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_COMMAND_BYTES,
            "MCP stdio command",
            false,
        )?;
        let cwd = bounded_text(
            object
                .get("cwd")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_COMMAND_BYTES,
            "MCP working directory",
            false,
        )?;
        let url = bounded_text(
            object
                .get("url")
                .or_else(|| object.get("server_url"))
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_COMMAND_BYTES,
            "MCP server URL",
            false,
        )?;
        if !url.is_empty() {
            validate_http_url(&url)?;
        }
        let connector_id = bounded_text(
            object
                .get("connector_id")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_LABEL_BYTES,
            "MCP connector ID",
            false,
        )?;
        let authorization = bounded_text(
            object
                .get("authorization")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            MAX_AUTHORIZATION_BYTES,
            "MCP authorization",
            false,
        )?;
        let args = string_list(object.get("args"), MAX_ARGUMENT_BYTES, "MCP arguments")?;
        let allowed_tools = string_list(
            object.get("allowed_tools"),
            MAX_LABEL_BYTES,
            "MCP allowed tools",
        )?;
        let require_approval = match object
            .get("require_approval")
            .and_then(Value::as_str)
            .unwrap_or("always")
            .trim()
            .to_ascii_lowercase()
            .as_str()
        {
            "never" => "never",
            _ => "always",
        }
        .to_owned();
        let timeout_seconds = value_i64(object.get("timeout_seconds"), 30).clamp(3, 120) as u64;
        let env = environment_map(object.get("env"))?;
        Ok(Self {
            enabled: object
                .get("enabled")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            label,
            description,
            transport,
            command,
            args,
            cwd,
            url,
            connector_id,
            authorization,
            allowed_tools,
            require_approval,
            timeout_seconds,
            env,
        })
    }

    fn to_value(&self) -> Value {
        json!({
            "enabled": self.enabled,
            "label": self.label,
            "description": self.description,
            "transport": match self.transport {
                McpTransport::Stdio => "stdio",
                McpTransport::Http => "http",
                McpTransport::Native => "native",
            },
            "command": self.command,
            "args": self.args,
            "cwd": self.cwd,
            "url": self.url,
            "connector_id": self.connector_id,
            "authorization": self.authorization,
            "allowed_tools": self.allowed_tools,
            "require_approval": self.require_approval,
            "timeout_seconds": self.timeout_seconds,
            "env": self.env,
        })
    }

    fn can_use_native(&self, settings: &NativeMcpSettings, mode: LlmApiMode) -> bool {
        settings.use_native
            && mode == LlmApiMode::Responses
            && self.transport != McpTransport::Stdio
            && (!self.url.is_empty() || !self.connector_id.is_empty())
            && self.require_approval == "never"
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeMcpSettings {
    pub enabled: bool,
    pub use_native: bool,
    servers: Vec<McpServerConfig>,
}

impl NativeMcpSettings {
    pub fn from_config(config: &ConfigDocument) -> Self {
        let servers = config
            .get("llm_mcp_servers")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|value| McpServerConfig::from_value(value).ok())
            .take(MAX_MCP_SERVERS)
            .collect();
        Self {
            enabled: config
                .get("llm_mcp_enabled")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            use_native: config
                .get("llm_mcp_use_native")
                .and_then(Value::as_bool)
                .unwrap_or(true),
            servers,
        }
    }
}

pub fn normalize_mcp_servers(value: &Value) -> Result<Vec<Value>, String> {
    let items = value
        .as_array()
        .ok_or_else(|| "MCP server configuration must be an array".to_owned())?;
    if items.len() > MAX_MCP_SERVERS {
        return Err(format!(
            "at most {MAX_MCP_SERVERS} MCP servers can be configured"
        ));
    }
    let mut labels = HashSet::new();
    let mut result = Vec::with_capacity(items.len());
    for item in items {
        let server = McpServerConfig::from_value(item)?;
        if !labels.insert(server.label.clone()) {
            return Err(format!("duplicate MCP server label: {}", server.label));
        }
        result.push(server.to_value());
    }
    Ok(result)
}

#[derive(Clone, Debug)]
enum McpToolBinding {
    Call {
        client_index: usize,
        tool_name: String,
        server_label: String,
        require_approval: String,
    },
    Error(String),
}

#[derive(Debug)]
enum McpClient {
    Http(Box<HttpMcpClient>),
    Stdio(Box<StdioMcpClient>),
}

impl McpClient {
    async fn connect(
        server: &McpServerConfig,
        base_dir: &Path,
        cancellation: &CancellationToken,
    ) -> Result<Self, String> {
        match server.transport {
            McpTransport::Http => Ok(Self::Http(Box::new(HttpMcpClient::new(server)?))),
            McpTransport::Stdio => Ok(Self::Stdio(Box::new(
                StdioMcpClient::start(server, base_dir, cancellation).await?,
            ))),
            McpTransport::Native => Err("native-only MCP is handled by the provider".to_owned()),
        }
    }

    async fn list_tools(&mut self, cancellation: &CancellationToken) -> Result<Vec<Value>, String> {
        match self {
            Self::Http(client) => client.list_tools(cancellation).await,
            Self::Stdio(client) => client.list_tools(cancellation).await,
        }
    }

    async fn call_tool(
        &mut self,
        name: &str,
        arguments: &Map<String, Value>,
        cancellation: &CancellationToken,
    ) -> Result<String, String> {
        match self {
            Self::Http(client) => client.call_tool(name, arguments, cancellation).await,
            Self::Stdio(client) => client.call_tool(name, arguments, cancellation).await,
        }
    }
}

#[derive(Debug, Default)]
pub struct NativeMcpRuntime {
    tool_definitions: Vec<Value>,
    bindings: HashMap<String, McpToolBinding>,
    clients: Vec<McpClient>,
}

impl NativeMcpRuntime {
    pub async fn prepare_from_path(
        config_path: &Path,
        mode: LlmApiMode,
        cancellation: &CancellationToken,
    ) -> Result<Self, String> {
        let config = ConfigDocument::load(config_path)
            .map_err(|error| format!("MCP configuration load failed: {error}"))?;
        let base_dir = config_path.parent().unwrap_or_else(|| Path::new("."));
        Ok(Self::prepare(&config, mode, base_dir, cancellation).await)
    }

    pub async fn prepare(
        config: &ConfigDocument,
        mode: LlmApiMode,
        base_dir: &Path,
        cancellation: &CancellationToken,
    ) -> Self {
        let settings = NativeMcpSettings::from_config(config);
        let mut runtime = Self::default();
        if !settings.enabled {
            return runtime;
        }
        for server in settings
            .servers
            .iter()
            .filter(|server| server.enabled)
            .take(MAX_MCP_SERVERS)
        {
            if cancellation.is_cancelled() {
                break;
            }
            if server.can_use_native(&settings, mode) {
                runtime
                    .tool_definitions
                    .push(native_tool_definition(server));
                continue;
            }
            if server.transport == McpTransport::Native {
                continue;
            }
            let mut client = match McpClient::connect(server, base_dir, cancellation).await {
                Ok(client) => client,
                Err(error) => {
                    runtime.push_error_tool(server, &error);
                    continue;
                }
            };
            let tools = match client.list_tools(cancellation).await {
                Ok(tools) => tools,
                Err(error) => {
                    runtime.push_error_tool(server, &error);
                    continue;
                }
            };
            let client_index = runtime.clients.len();
            runtime.clients.push(client);
            let allowed = server.allowed_tools.iter().collect::<HashSet<_>>();
            for item in tools.into_iter().take(MAX_MCP_TOOLS_PER_SERVER) {
                if runtime.bindings.len() >= MAX_MCP_TOOLS_TOTAL {
                    break;
                }
                let Some(tool_name) = item.get("name").and_then(Value::as_str) else {
                    continue;
                };
                let tool_name = tool_name.trim();
                if tool_name.is_empty()
                    || tool_name.len() > MAX_LABEL_BYTES
                    || (!allowed.is_empty() && !allowed.contains(&tool_name.to_owned()))
                {
                    continue;
                }
                let public_name = public_tool_name(&server.label, tool_name);
                let schema = item
                    .get("inputSchema")
                    .or_else(|| item.get("input_schema"))
                    .filter(|value| value.is_object())
                    .cloned()
                    .unwrap_or_else(|| json!({"type":"object","properties":{}}));
                let description = item
                    .get("description")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim();
                runtime.tool_definitions.push(json!({
                    "type":"function",
                    "function":{
                        "name":public_name,
                        "description": if description.is_empty() {
                            format!("Call MCP tool {tool_name} on server {}.", server.label)
                        } else {
                            format!("[MCP:{}] {description}", server.label)
                        },
                        "parameters":schema,
                    }
                }));
                runtime.bindings.insert(
                    public_name,
                    McpToolBinding::Call {
                        client_index,
                        tool_name: tool_name.to_owned(),
                        server_label: server.label.clone(),
                        require_approval: server.require_approval.clone(),
                    },
                );
            }
        }
        runtime
    }

    pub fn tool_definitions(&self) -> &[Value] {
        &self.tool_definitions
    }

    pub fn handles(&self, public_name: &str) -> bool {
        self.bindings.contains_key(public_name)
    }

    pub async fn execute(
        &mut self,
        public_name: &str,
        arguments: &Map<String, Value>,
        cancellation: &CancellationToken,
    ) -> Result<String, String> {
        let binding =
            self.bindings.get(public_name).cloned().ok_or_else(|| {
                format!("MCP tool is not available in this request: {public_name}")
            })?;
        match binding {
            McpToolBinding::Error(error) => Err(error),
            McpToolBinding::Call {
                client_index,
                tool_name,
                server_label,
                require_approval,
            } => {
                if require_approval == "always" {
                    return Err(format!(
                        "MCP tool blocked by approval setting: {server_label}/{tool_name}"
                    ));
                }
                let client = self
                    .clients
                    .get_mut(client_index)
                    .ok_or_else(|| "MCP client is no longer available".to_owned())?;
                client.call_tool(&tool_name, arguments, cancellation).await
            }
        }
    }

    fn push_error_tool(&mut self, server: &McpServerConfig, error: &str) {
        if self.bindings.len() >= MAX_MCP_TOOLS_TOTAL {
            return;
        }
        let name = format!(
            "{}{}__status",
            MCP_TOOL_PREFIX,
            safe_tool_component(&server.label)
        );
        let name: String = name.chars().take(64).collect();
        let message = format!("MCP server {} is not available: {error}", server.label);
        self.tool_definitions.push(json!({
            "type":"function",
            "function":{
                "name":name,
                "description":message,
                "parameters":{"type":"object","properties":{}},
            }
        }));
        self.bindings.insert(name, McpToolBinding::Error(message));
    }
}

fn native_tool_definition(server: &McpServerConfig) -> Value {
    let mut tool = Map::from_iter([
        ("type".to_owned(), Value::String("mcp".to_owned())),
        (
            "server_label".to_owned(),
            Value::String(server.label.clone()),
        ),
        (
            "require_approval".to_owned(),
            Value::String("never".to_owned()),
        ),
    ]);
    if !server.description.is_empty() {
        tool.insert(
            "server_description".to_owned(),
            Value::String(server.description.clone()),
        );
    }
    if !server.connector_id.is_empty() {
        tool.insert(
            "connector_id".to_owned(),
            Value::String(server.connector_id.clone()),
        );
    } else {
        tool.insert("server_url".to_owned(), Value::String(server.url.clone()));
    }
    if !server.authorization.is_empty() {
        tool.insert(
            "authorization".to_owned(),
            Value::String(server.authorization.clone()),
        );
    }
    if !server.allowed_tools.is_empty() {
        tool.insert(
            "allowed_tools".to_owned(),
            serde_json::to_value(&server.allowed_tools).expect("string list serialization"),
        );
    }
    Value::Object(tool)
}

#[derive(Debug)]
struct HttpMcpClient {
    server: McpServerConfig,
    client: reqwest::Client,
    initialized: bool,
    session_id: String,
    protocol_version: String,
    next_id: u64,
}

impl HttpMcpClient {
    fn new(server: &McpServerConfig) -> Result<Self, String> {
        if server.url.is_empty() {
            return Err("HTTP MCP server URL is empty".to_owned());
        }
        validate_http_url(&server.url)?;
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .timeout(Duration::from_secs(server.timeout_seconds))
            .build()
            .map_err(|error| format!("HTTP MCP client creation failed: {error}"))?;
        Ok(Self {
            server: server.clone(),
            client,
            initialized: false,
            session_id: String::new(),
            protocol_version: MCP_PROTOCOL_VERSION.to_owned(),
            next_id: 1,
        })
    }

    async fn ensure_initialized(&mut self, cancellation: &CancellationToken) -> Result<(), String> {
        if self.initialized {
            return Ok(());
        }
        let response = self
            .request_rpc(
                "initialize",
                Some(json!({
                    "protocolVersion":MCP_PROTOCOL_VERSION,
                    "capabilities":{},
                    "clientInfo":{"name":"BandoriPet","version":"1.0"},
                })),
                cancellation,
            )
            .await?;
        if let Some(version) = response
            .get("result")
            .and_then(|result| result.get("protocolVersion"))
            .and_then(Value::as_str)
        {
            self.protocol_version = version.to_owned();
        }
        response_result(&response)?;
        self.notify("notifications/initialized", json!({}), cancellation)
            .await?;
        self.initialized = true;
        Ok(())
    }

    async fn list_tools(&mut self, cancellation: &CancellationToken) -> Result<Vec<Value>, String> {
        self.ensure_initialized(cancellation).await?;
        let response = self
            .request_rpc("tools/list", Some(json!({})), cancellation)
            .await?;
        let result = response_result(&response)?;
        Ok(result
            .get("tools")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    async fn call_tool(
        &mut self,
        name: &str,
        arguments: &Map<String, Value>,
        cancellation: &CancellationToken,
    ) -> Result<String, String> {
        self.ensure_initialized(cancellation).await?;
        let response = self
            .request_rpc(
                "tools/call",
                Some(json!({"name":name,"arguments":arguments})),
                cancellation,
            )
            .await?;
        Ok(mcp_result_text(response_result(&response)?))
    }

    async fn request_rpc(
        &mut self,
        method: &str,
        params: Option<Value>,
        cancellation: &CancellationToken,
    ) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id = self.next_id.saturating_add(1);
        let mut payload = Map::from_iter([
            ("jsonrpc".to_owned(), Value::String("2.0".to_owned())),
            ("id".to_owned(), Value::from(id)),
            ("method".to_owned(), Value::String(method.to_owned())),
        ]);
        if let Some(params) = params {
            payload.insert("params".to_owned(), params);
        }
        self.post(Value::Object(payload), Some(id), cancellation)
            .await
    }

    async fn notify(
        &mut self,
        method: &str,
        params: Value,
        cancellation: &CancellationToken,
    ) -> Result<(), String> {
        self.post(
            json!({"jsonrpc":"2.0","method":method,"params":params}),
            None,
            cancellation,
        )
        .await
        .map(|_| ())
    }

    async fn post(
        &mut self,
        payload: Value,
        expected_id: Option<u64>,
        cancellation: &CancellationToken,
    ) -> Result<Value, String> {
        let mut request = self
            .client
            .post(&self.server.url)
            .header(CONTENT_TYPE, "application/json")
            .header(ACCEPT, "application/json, text/event-stream");
        if !self.server.authorization.is_empty() {
            let authorization = if self
                .server
                .authorization
                .to_ascii_lowercase()
                .starts_with("bearer ")
            {
                self.server.authorization.clone()
            } else {
                format!("Bearer {}", self.server.authorization)
            };
            request = request.header(
                AUTHORIZATION,
                HeaderValue::from_str(&authorization)
                    .map_err(|_| "MCP authorization header is invalid".to_owned())?,
            );
        }
        if payload.get("method").and_then(Value::as_str) != Some("initialize") {
            request = request.header("mcp-protocol-version", &self.protocol_version);
            if !self.session_id.is_empty() {
                request = request.header("mcp-session-id", &self.session_id);
            }
        }
        let response = tokio::select! {
            _ = cancellation.cancelled() => return Err("MCP request cancelled".to_owned()),
            response = request.json(&payload).send() => response.map_err(|error| format!("MCP HTTP request failed: {error}"))?,
        };
        if response.status().is_redirection() {
            return Err(
                "MCP HTTP redirects are blocked to avoid forwarding authorization".to_owned(),
            );
        }
        let status = response.status();
        if let Some(session_id) = response
            .headers()
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok())
        {
            self.session_id = session_id.chars().take(512).collect();
        }
        if let Some(length) = response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<usize>().ok())
            && length > MAX_MCP_MESSAGE_BYTES
        {
            return Err("MCP HTTP response exceeds the 4 MiB limit".to_owned());
        }
        let mut response = response;
        let mut body = Vec::new();
        loop {
            let chunk = tokio::select! {
                _ = cancellation.cancelled() => return Err("MCP request cancelled".to_owned()),
                chunk = response.chunk() => chunk.map_err(|error| format!("MCP HTTP response failed: {error}"))?,
            };
            let Some(chunk) = chunk else {
                break;
            };
            if body.len().saturating_add(chunk.len()) > MAX_MCP_MESSAGE_BYTES {
                return Err("MCP HTTP response exceeds the 4 MiB limit".to_owned());
            }
            body.extend_from_slice(&chunk);
        }
        let raw = String::from_utf8_lossy(&body).trim().to_owned();
        if !status.is_success() {
            return Err(format!(
                "MCP HTTP server returned {status}: {}",
                raw.chars().take(1000).collect::<String>()
            ));
        }
        if raw.is_empty() {
            return Ok(json!({}));
        }
        parse_http_response(&raw, expected_id)
    }
}

#[derive(Debug)]
struct StdioMcpClient {
    server: McpServerConfig,
    child: Child,
    stdin: ChildStdin,
    stdout: ChildStdout,
    buffer: Vec<u8>,
    next_id: u64,
}

impl StdioMcpClient {
    async fn start(
        server: &McpServerConfig,
        base_dir: &Path,
        cancellation: &CancellationToken,
    ) -> Result<Self, String> {
        if server.command.is_empty() {
            return Err("stdio MCP command is empty".to_owned());
        }
        let cwd = resolve_cwd(&server.cwd, base_dir)?;
        let mut command = Command::new(&server.command);
        command
            .args(&server.args)
            .current_dir(cwd)
            .envs(&server.env)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            command.as_std_mut().creation_flags(0x0800_0000);
        }
        let mut child = command
            .spawn()
            .map_err(|error| format!("MCP server process could not be started: {error}"))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "MCP server stdin is unavailable".to_owned())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "MCP server stdout is unavailable".to_owned())?;
        let mut client = Self {
            server: server.clone(),
            child,
            stdin,
            stdout,
            buffer: Vec::new(),
            next_id: 1,
        };
        let response = client
            .request(
                "initialize",
                json!({
                    "protocolVersion":MCP_PROTOCOL_VERSION,
                    "capabilities":{},
                    "clientInfo":{"name":"BandoriPet","version":"1.0"},
                }),
                cancellation,
            )
            .await?;
        response_result(&response)?;
        client
            .write_message(&json!({
                "jsonrpc":"2.0",
                "method":"notifications/initialized",
                "params":{},
            }))
            .await?;
        Ok(client)
    }

    async fn list_tools(&mut self, cancellation: &CancellationToken) -> Result<Vec<Value>, String> {
        let response = self.request("tools/list", json!({}), cancellation).await?;
        let result = response_result(&response)?;
        Ok(result
            .get("tools")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    async fn call_tool(
        &mut self,
        name: &str,
        arguments: &Map<String, Value>,
        cancellation: &CancellationToken,
    ) -> Result<String, String> {
        let response = self
            .request(
                "tools/call",
                json!({"name":name,"arguments":arguments}),
                cancellation,
            )
            .await?;
        Ok(mcp_result_text(response_result(&response)?))
    }

    async fn request(
        &mut self,
        method: &str,
        params: Value,
        cancellation: &CancellationToken,
    ) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id = self.next_id.saturating_add(1);
        self.write_message(&json!({
            "jsonrpc":"2.0",
            "id":id,
            "method":method,
            "params":params,
        }))
        .await?;
        let timeout = Duration::from_secs(self.server.timeout_seconds);
        let result = tokio::select! {
            _ = cancellation.cancelled() => Err("MCP request cancelled".to_owned()),
            result = tokio::time::timeout(timeout, self.read_response(id)) => {
                result.map_err(|_| format!("MCP request timed out: {method}"))?
            }
        };
        if result.is_err() {
            let _ = self.child.start_kill();
        }
        result
    }

    async fn write_message(&mut self, message: &Value) -> Result<(), String> {
        let mut payload = serde_json::to_vec(message)
            .map_err(|error| format!("MCP request serialization failed: {error}"))?;
        if payload.len() > MAX_MCP_MESSAGE_BYTES {
            return Err("MCP request exceeds the 4 MiB limit".to_owned());
        }
        payload.push(b'\n');
        self.stdin
            .write_all(&payload)
            .await
            .map_err(|error| format!("MCP server stdin write failed: {error}"))?;
        self.stdin
            .flush()
            .await
            .map_err(|error| format!("MCP server stdin flush failed: {error}"))
    }

    async fn read_response(&mut self, expected_id: u64) -> Result<Value, String> {
        loop {
            while let Some(message) = extract_stdio_message(&mut self.buffer)? {
                if message.get("id").and_then(Value::as_u64) == Some(expected_id) {
                    return Ok(message);
                }
            }
            let mut chunk = [0u8; 4096];
            let count = self
                .stdout
                .read(&mut chunk)
                .await
                .map_err(|error| format!("MCP server stdout read failed: {error}"))?;
            if count == 0 {
                return Err("MCP server stdout closed before the response".to_owned());
            }
            if self.buffer.len().saturating_add(count) > MAX_MCP_MESSAGE_BYTES {
                return Err("MCP stdio response exceeds the 4 MiB limit".to_owned());
            }
            self.buffer.extend_from_slice(&chunk[..count]);
        }
    }
}

fn extract_stdio_message(buffer: &mut Vec<u8>) -> Result<Option<Value>, String> {
    while buffer.starts_with(b"\r") || buffer.starts_with(b"\n") {
        buffer.remove(0);
    }
    if buffer.is_empty() {
        return Ok(None);
    }
    let lower_prefix =
        String::from_utf8_lossy(&buffer[..buffer.len().min(32)]).to_ascii_lowercase();
    if lower_prefix.starts_with("content-length:") {
        let Some(header_end) = find_bytes(buffer, b"\r\n\r\n") else {
            return Ok(None);
        };
        let headers = String::from_utf8_lossy(&buffer[..header_end]);
        let content_length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.trim()
                    .eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().ok())
                    .flatten()
            })
            .ok_or_else(|| "MCP response has invalid Content-Length".to_owned())?;
        if content_length > MAX_MCP_MESSAGE_BYTES {
            return Err("MCP stdio response exceeds the 4 MiB limit".to_owned());
        }
        let body_start = header_end + 4;
        let body_end = body_start.saturating_add(content_length);
        if buffer.len() < body_end {
            return Ok(None);
        }
        let message = serde_json::from_slice(&buffer[body_start..body_end])
            .map_err(|error| format!("MCP stdio response is invalid JSON: {error}"))?;
        buffer.drain(..body_end);
        return Ok(Some(message));
    }
    let Some(line_end) = buffer.iter().position(|value| *value == b'\n') else {
        return Ok(None);
    };
    let line = buffer[..line_end]
        .strip_suffix(b"\r")
        .unwrap_or(&buffer[..line_end]);
    let message = serde_json::from_slice(line)
        .map_err(|error| format!("MCP stdio response is invalid JSON: {error}"))?;
    buffer.drain(..=line_end);
    Ok(Some(message))
}

fn parse_http_response(raw: &str, expected_id: Option<u64>) -> Result<Value, String> {
    if !raw.starts_with("event:") && !raw.starts_with("data:") && !raw.contains("\ndata:") {
        return serde_json::from_str(raw)
            .map_err(|error| format!("MCP HTTP response is invalid JSON: {error}"));
    }
    for block in raw.replace("\r\n", "\n").split("\n\n") {
        let data = block
            .lines()
            .filter_map(|line| line.strip_prefix("data:"))
            .map(str::trim_start)
            .collect::<Vec<_>>()
            .join("\n");
        if data.is_empty() || data == "[DONE]" {
            continue;
        }
        let Ok(message) = serde_json::from_str::<Value>(&data) else {
            continue;
        };
        if expected_id.is_none() || message.get("id").and_then(Value::as_u64) == expected_id {
            return Ok(message);
        }
    }
    Err("MCP HTTP server returned no matching response event".to_owned())
}

fn response_result(response: &Value) -> Result<&Value, String> {
    if let Some(error) = response.get("error").filter(|value| !value.is_null()) {
        return Err(format!("MCP JSON-RPC error: {error}"));
    }
    response
        .get("result")
        .ok_or_else(|| "MCP JSON-RPC response is missing result".to_owned())
}

fn mcp_result_text(result: &Value) -> String {
    let Some(object) = result.as_object() else {
        return bounded_result(result.to_string());
    };
    let mut parts = Vec::new();
    for item in object
        .get("content")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        match item.get("type").and_then(Value::as_str) {
            Some("text") => {
                if let Some(text) = item.get("text").and_then(Value::as_str) {
                    parts.push(text.to_owned());
                }
            }
            Some("image") => parts.push("[MCP image output omitted]".to_owned()),
            _ if item.is_object() => parts.push(item.to_string()),
            _ => {}
        }
    }
    if let Some(structured) = object.get("structuredContent") {
        parts.push(structured.to_string());
    }
    let fallback = result.to_string();
    let body = parts
        .into_iter()
        .filter(|part| !part.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n");
    let prefix = if object
        .get("isError")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        "MCP tool returned an error: "
    } else {
        ""
    };
    bounded_result(format!(
        "{prefix}{}",
        if body.is_empty() { &fallback } else { &body }
    ))
}

fn bounded_result(value: String) -> String {
    value.chars().take(MAX_MCP_RESULT_CHARS).collect()
}

fn public_tool_name(label: &str, tool_name: &str) -> String {
    format!(
        "{}{}__{}",
        MCP_TOOL_PREFIX,
        safe_tool_component(label),
        safe_tool_component(tool_name)
    )
    .chars()
    .take(64)
    .collect()
}

fn safe_tool_component(value: &str) -> String {
    let mut cleaned = String::new();
    let mut previous_separator = false;
    for character in value.trim().chars() {
        if character.is_ascii_alphanumeric() || matches!(character, '_' | '-') {
            cleaned.push(character);
            previous_separator = false;
        } else if !previous_separator {
            cleaned.push('_');
            previous_separator = true;
        }
    }
    let cleaned = cleaned.trim_matches('_');
    if cleaned.is_empty() {
        "tool".to_owned()
    } else {
        cleaned.to_owned()
    }
}

fn validate_http_url(value: &str) -> Result<(), String> {
    let url = Url::parse(value).map_err(|_| "MCP URL must be a complete HTTP(S) URL".to_owned())?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err("MCP URL must be a complete HTTP(S) URL".to_owned());
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("MCP URL cannot contain credentials".to_owned());
    }
    Ok(())
}

fn resolve_cwd(value: &str, base_dir: &Path) -> Result<PathBuf, String> {
    let path = if value.trim().is_empty() {
        base_dir.to_owned()
    } else {
        let path = PathBuf::from(value.trim());
        if path.is_absolute() {
            path
        } else {
            base_dir.join(path)
        }
    };
    if !path.is_dir() {
        return Err(format!(
            "MCP working directory does not exist: {}",
            path.display()
        ));
    }
    Ok(path)
}

fn string_list(
    value: Option<&Value>,
    max_bytes: usize,
    label: &str,
) -> Result<Vec<String>, String> {
    let mut values = Vec::new();
    match value {
        None | Some(Value::Null) => {}
        Some(Value::String(value)) => {
            values.extend(
                value
                    .split(' ')
                    .filter(|value| !value.is_empty())
                    .map(str::to_owned),
            );
        }
        Some(Value::Array(items)) => {
            for item in items {
                let item = item
                    .as_str()
                    .ok_or_else(|| format!("{label} must contain only strings"))?;
                if !item.is_empty() {
                    values.push(item.to_owned());
                }
            }
        }
        Some(_) => return Err(format!("{label} must be a string or array")),
    }
    if values.len() > MAX_MCP_TOOLS_PER_SERVER {
        return Err(format!("{label} contains too many entries"));
    }
    for value in &values {
        bounded_text(value, max_bytes, label, false)?;
    }
    Ok(values)
}

fn environment_map(value: Option<&Value>) -> Result<BTreeMap<String, String>, String> {
    let Some(object) = value.and_then(Value::as_object) else {
        return Ok(BTreeMap::new());
    };
    if object.len() > MAX_ENV_ENTRIES {
        return Err(format!("MCP environment exceeds {MAX_ENV_ENTRIES} entries"));
    }
    let mut env = BTreeMap::new();
    for (key, value) in object {
        let key = bounded_text(key, MAX_ENV_KEY_BYTES, "MCP environment key", false)?;
        if key.is_empty() || key.contains('=') {
            return Err("MCP environment key is empty or contains '='".to_owned());
        }
        let value = value
            .as_str()
            .ok_or_else(|| "MCP environment values must be strings".to_owned())?;
        env.insert(
            key,
            bounded_text(value, MAX_ENV_VALUE_BYTES, "MCP environment value", true)?,
        );
    }
    Ok(env)
}

fn bounded_text(
    value: &str,
    max_bytes: usize,
    label: &str,
    allow_newlines: bool,
) -> Result<String, String> {
    let value = value.trim();
    let invalid_control = value.chars().any(|character| {
        character.is_control() && !(allow_newlines && matches!(character, '\n' | '\r' | '\t'))
    });
    if value.len() > max_bytes || invalid_control {
        return Err(format!(
            "{label} is too long or contains control characters"
        ));
    }
    Ok(value.to_owned())
}

fn value_i64(value: Option<&Value>, default: i64) -> i64 {
    value
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
        })
        .unwrap_or(default)
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    fn server(transport: &str) -> Value {
        json!({
            "enabled":true,
            "label":"files demo",
            "description":"test server",
            "transport":transport,
            "command":"fixture-server",
            "args":["--stdio"],
            "cwd":"",
            "url":"http://127.0.0.1:8765/mcp",
            "connector_id":"",
            "authorization":"secret",
            "allowed_tools":["read_file"],
            "require_approval":"never",
            "timeout_seconds":1,
            "env":{"TOKEN":"value"}
        })
    }

    #[test]
    fn settings_normalize_like_python_and_reject_duplicate_labels() {
        let normalized = normalize_mcp_servers(&json!([server("http")])).unwrap();
        assert_eq!(normalized[0]["transport"], "http");
        assert_eq!(normalized[0]["timeout_seconds"], 3);
        assert_eq!(normalized[0]["allowed_tools"], json!(["read_file"]));
        assert!(normalize_mcp_servers(&json!([server("http"), server("stdio")])).is_err());
    }

    #[test]
    fn public_names_and_stdio_framing_are_bounded_and_compatible() {
        assert_eq!(
            public_tool_name("files demo", "read file"),
            "mcp__files_demo__read_file"
        );
        let message = json!({"jsonrpc":"2.0","id":7,"result":{}});
        let body = serde_json::to_vec(&message).unwrap();
        let mut framed = format!("Content-Length: {}\r\n\r\n", body.len()).into_bytes();
        framed.extend(body);
        assert_eq!(extract_stdio_message(&mut framed).unwrap(), Some(message));
        assert!(framed.is_empty());

        let mut line = b"{\"jsonrpc\":\"2.0\",\"id\":8,\"result\":{}}\n".to_vec();
        assert_eq!(extract_stdio_message(&mut line).unwrap().unwrap()["id"], 8);
    }

    #[tokio::test]
    async fn responses_mode_uses_provider_native_mcp_without_local_discovery() {
        let mut config = ConfigDocument::default();
        config.set("llm_mcp_enabled", Value::Bool(true));
        config.set("llm_mcp_use_native", Value::Bool(true));
        config.set("llm_mcp_servers", json!([server("http")]));
        let runtime = NativeMcpRuntime::prepare(
            &config,
            LlmApiMode::Responses,
            Path::new("."),
            &CancellationToken::new(),
        )
        .await;
        assert_eq!(runtime.tool_definitions().len(), 1);
        assert_eq!(runtime.tool_definitions()[0]["type"], "mcp");
        assert_eq!(runtime.tool_definitions()[0]["server_label"], "files demo");
        assert_eq!(runtime.tool_definitions()[0]["authorization"], "secret");
        assert!(runtime.bindings.is_empty());
    }

    #[tokio::test]
    async fn http_proxy_discovers_and_calls_tools_with_session_headers() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server_task = tokio::spawn(async move {
            let mut methods = Vec::new();
            for _ in 0..4 {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                let mut chunk = [0u8; 4096];
                let header_end = loop {
                    let count = stream.read(&mut chunk).await.unwrap();
                    assert!(count > 0);
                    request.extend_from_slice(&chunk[..count]);
                    if let Some(index) = find_bytes(&request, b"\r\n\r\n") {
                        break index;
                    }
                };
                let headers = String::from_utf8_lossy(&request[..header_end]).to_string();
                let content_length = headers
                    .lines()
                    .find_map(|line| {
                        let (name, value) = line.split_once(':')?;
                        name.eq_ignore_ascii_case("content-length")
                            .then(|| value.trim().parse::<usize>().unwrap())
                    })
                    .unwrap();
                let body_start = header_end + 4;
                while request.len() < body_start + content_length {
                    let count = stream.read(&mut chunk).await.unwrap();
                    assert!(count > 0);
                    request.extend_from_slice(&chunk[..count]);
                }
                let payload: Value =
                    serde_json::from_slice(&request[body_start..body_start + content_length])
                        .unwrap();
                let method = payload["method"].as_str().unwrap().to_owned();
                methods.push(method.clone());
                assert!(
                    headers
                        .to_ascii_lowercase()
                        .contains("authorization: bearer secret")
                );
                if method != "initialize" {
                    let lower = headers.to_ascii_lowercase();
                    assert!(lower.contains("mcp-protocol-version: 2025-06-18"));
                    assert!(lower.contains("mcp-session-id: fixture-session"));
                }
                let id = payload.get("id").cloned().unwrap_or(Value::Null);
                let response = match method.as_str() {
                    "initialize" => json!({
                        "jsonrpc":"2.0","id":id,
                        "result":{"protocolVersion":MCP_PROTOCOL_VERSION}
                    }),
                    "notifications/initialized" => json!({}),
                    "tools/list" => json!({
                        "jsonrpc":"2.0","id":id,
                        "result":{"tools":[{
                            "name":"read_file",
                            "description":"Read a fixture file",
                            "inputSchema":{"type":"object","properties":{"path":{"type":"string"}}}
                        }]}
                    }),
                    "tools/call" => {
                        assert_eq!(payload["params"]["name"], "read_file");
                        assert_eq!(payload["params"]["arguments"]["path"], "notes.txt");
                        json!({
                            "jsonrpc":"2.0","id":id,
                            "result":{"content":[{"type":"text","text":"fixture contents"}]}
                        })
                    }
                    _ => unreachable!(),
                };
                let body = response.to_string();
                let wire = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nMcp-Session-Id: fixture-session\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                stream.write_all(wire.as_bytes()).await.unwrap();
            }
            methods
        });

        let mut configured_server = server("http");
        configured_server["url"] = Value::String(format!("http://{address}/mcp"));
        let mut config = ConfigDocument::default();
        config.set("llm_mcp_enabled", Value::Bool(true));
        config.set("llm_mcp_use_native", Value::Bool(true));
        config.set("llm_mcp_servers", json!([configured_server]));
        let cancellation = CancellationToken::new();
        let mut runtime = NativeMcpRuntime::prepare(
            &config,
            LlmApiMode::ChatCompletions,
            Path::new("."),
            &cancellation,
        )
        .await;
        assert_eq!(runtime.tool_definitions().len(), 1);
        assert_eq!(
            runtime.tool_definitions()[0]["function"]["name"],
            "mcp__files_demo__read_file"
        );
        let result = runtime
            .execute(
                "mcp__files_demo__read_file",
                &Map::from_iter([("path".to_owned(), Value::String("notes.txt".to_owned()))]),
                &cancellation,
            )
            .await
            .unwrap();
        assert_eq!(result, "fixture contents");
        assert_eq!(
            server_task.await.unwrap(),
            [
                "initialize",
                "notifications/initialized",
                "tools/list",
                "tools/call"
            ]
        );
    }

    #[test]
    fn result_text_preserves_text_structured_content_and_error_state() {
        let text = mcp_result_text(&json!({
            "isError":true,
            "content":[
                {"type":"text","text":"failed"},
                {"type":"image","data":"hidden"}
            ],
            "structuredContent":{"code":7}
        }));
        assert!(text.starts_with("MCP tool returned an error: failed"));
        assert!(text.contains("[MCP image output omitted]"));
        assert!(text.contains("\"code\":7"));
        assert!(!text.contains("hidden"));
    }
}
