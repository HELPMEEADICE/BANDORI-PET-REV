use crate::config::ConfigDocument;
use crate::reminder::LocalDateTime;
use reqwest::Client;
use reqwest::header::{
    ACCEPT, ACCEPT_LANGUAGE, CONTENT_LENGTH, CONTENT_TYPE, LOCATION, USER_AGENT,
};
use serde_json::Value;
use std::collections::HashSet;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::time::Duration;
use tokio::net::lookup_host;
use tokio_util::sync::CancellationToken;
use url::Url;

pub const WEB_SEARCH_TOOL_NAME: &str = "web_search";
pub const WEB_FETCH_TOOL_NAME: &str = "web_fetch";

const MAX_REDIRECTS: usize = 5;
const MAX_SEARCH_BODY_BYTES: usize = 2 * 1024 * 1024;
const MAX_FETCH_BODY_BYTES: usize = 512 * 1024;
const MAX_PAGE_EXCERPT_CHARS: usize = 700;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(12);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WebSearchEngine {
    Bing,
    BingCn,
    Google,
    DuckDuckGo,
    Baidu,
}

impl WebSearchEngine {
    pub fn parse(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "bing" => Self::Bing,
            "google" => Self::Google,
            "duckduckgo" => Self::DuckDuckGo,
            "baidu" => Self::Baidu,
            _ => Self::BingCn,
        }
    }

    pub fn key(self) -> &'static str {
        match self {
            Self::Bing => "bing",
            Self::BingCn => "bing_cn",
            Self::Google => "google",
            Self::DuckDuckGo => "duckduckgo",
            Self::Baidu => "baidu",
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Bing => "Bing",
            Self::BingCn => "Bing CN",
            Self::Google => "Google",
            Self::DuckDuckGo => "DuckDuckGo",
            Self::Baidu => "Baidu",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeWebToolSettings {
    pub search_enabled: bool,
    pub search_engine: WebSearchEngine,
    pub show_sources: bool,
    pub fetch_enabled: bool,
}

impl NativeWebToolSettings {
    pub fn from_config(config: &ConfigDocument) -> Self {
        Self {
            search_enabled: config_bool(config, "llm_web_search_enabled", false),
            search_engine: WebSearchEngine::parse(&config_string(config, "llm_web_search_engine")),
            show_sources: config_bool(config, "llm_web_search_show_sources", true),
            fetch_enabled: config_bool(config, "llm_web_fetch_enabled", false),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SearchResult {
    title: String,
    url: String,
    snippet: String,
    page_excerpt: String,
}

pub async fn web_search(
    query: &str,
    max_results: usize,
    engine: WebSearchEngine,
    now: LocalDateTime,
    cancellation: &CancellationToken,
) -> Result<String, String> {
    let query = query.trim();
    if query.is_empty() {
        return Err("搜索失败：query 不能为空。".to_owned());
    }
    if query.len() > 512 || query.chars().any(char::is_control) {
        return Err("搜索失败：query 过长或包含控制字符。".to_owned());
    }
    let max_results = max_results.clamp(1, 8);
    let mut errors = Vec::new();
    let mut selected_engine = engine;
    let mut results = match search_engine(query, max_results, engine, cancellation).await {
        Ok(results) => results,
        Err(error) => {
            errors.push(error);
            Vec::new()
        }
    };
    if results.is_empty() && engine != WebSearchEngine::DuckDuckGo {
        selected_engine = WebSearchEngine::DuckDuckGo;
        match search_engine(
            query,
            max_results,
            WebSearchEngine::DuckDuckGo,
            cancellation,
        )
        .await
        {
            Ok(fallback) => results = fallback,
            Err(error) => errors.push(error),
        }
    }
    if results.is_empty() {
        match search_duckduckgo_instant_answer(query, max_results, cancellation).await {
            Ok(fallback) => {
                selected_engine = WebSearchEngine::DuckDuckGo;
                results = fallback;
            }
            Err(error) => errors.push(error),
        }
    }
    if results.is_empty() {
        if errors.is_empty() {
            return Ok(format!("没有找到与 “{query}” 相关的搜索结果。"));
        }
        errors.dedup();
        return Err(format!(
            "搜索失败：{}",
            errors.into_iter().take(2).collect::<Vec<_>>().join("；")
        ));
    }

    let mut enriched = 0;
    for result in &mut results {
        if enriched >= 2 || cancellation.is_cancelled() {
            break;
        }
        if let Ok(page) =
            request_public_text(&result.url, 250_000, Duration::from_secs(4), cancellation).await
        {
            let excerpt = readable_text(&page, MAX_PAGE_EXCERPT_CHARS);
            if excerpt.chars().count() >= 80 {
                result.page_excerpt = excerpt;
                enriched += 1;
            }
        }
    }
    Ok(format_search_results(
        query,
        &results[..results.len().min(max_results)],
        selected_engine,
        now,
    ))
}

pub async fn web_fetch(
    source_url: &str,
    max_chars: usize,
    now: LocalDateTime,
    cancellation: &CancellationToken,
) -> Result<String, String> {
    let max_chars = max_chars.clamp(500, 12_000);
    let body_cap = MAX_FETCH_BODY_BYTES.min(250_000usize.max(max_chars.saturating_mul(40)));
    let (final_url, text) = request_public_text_with_final_url(
        source_url.trim(),
        body_cap,
        REQUEST_TIMEOUT,
        cancellation,
    )
    .await
    .map_err(|error| format!("网页读取失败：{error}"))?;
    let title = html_title(&text).unwrap_or_else(|| final_url.clone());
    let body = readable_text(&text, max_chars);
    if body.chars().count() < 40 {
        return Err("网页读取失败：没有提取到可读正文，或页面不是文本/HTML 内容。".to_owned());
    }
    Ok(format!(
        "1. {title}\nURL: {final_url}\n读取时间：{}\n正文：{body}",
        now.isoformat().replace('T', " ")
    ))
}

async fn search_engine(
    query: &str,
    max_results: usize,
    engine: WebSearchEngine,
    cancellation: &CancellationToken,
) -> Result<Vec<SearchResult>, String> {
    let encoded = form_encode(&[("q", query)]);
    let url = match engine {
        WebSearchEngine::Bing => format!("https://www.bing.com/search?{encoded}"),
        WebSearchEngine::BingCn => format!(
            "https://cn.bing.com/search?{}",
            form_encode(&[("q", query), ("mkt", "zh-CN"), ("setlang", "zh-CN")])
        ),
        WebSearchEngine::Google => format!(
            "https://www.google.com/search?{}",
            form_encode(&[("q", query), ("hl", "zh-CN")])
        ),
        WebSearchEngine::DuckDuckGo => {
            format!("https://html.duckduckgo.com/html/?{encoded}")
        }
        WebSearchEngine::Baidu => {
            format!("https://www.baidu.com/s?{}", form_encode(&[("wd", query)]))
        }
    };
    let html =
        request_public_text(&url, MAX_SEARCH_BODY_BYTES, REQUEST_TIMEOUT, cancellation).await?;
    let results = match engine {
        WebSearchEngine::Bing | WebSearchEngine::BingCn => parse_bing_results(&html, max_results),
        WebSearchEngine::Google => parse_google_results(&html, max_results),
        WebSearchEngine::DuckDuckGo => parse_duckduckgo_results(&html, max_results),
        WebSearchEngine::Baidu => parse_baidu_results(&html, max_results),
    };
    Ok(results)
}

async fn search_duckduckgo_instant_answer(
    query: &str,
    max_results: usize,
    cancellation: &CancellationToken,
) -> Result<Vec<SearchResult>, String> {
    let url = format!(
        "https://api.duckduckgo.com/?{}",
        form_encode(&[
            ("q", query),
            ("format", "json"),
            ("no_html", "1"),
            ("skip_disambig", "1"),
        ])
    );
    let body =
        request_public_text(&url, MAX_SEARCH_BODY_BYTES, REQUEST_TIMEOUT, cancellation).await?;
    let value: Value = serde_json::from_str(&body)
        .map_err(|error| format!("DuckDuckGo 返回了无效 JSON：{error}"))?;
    let mut results = Vec::new();
    let abstract_text = value["AbstractText"].as_str().unwrap_or_default().trim();
    let abstract_url = value["AbstractURL"].as_str().unwrap_or_default().trim();
    if !abstract_text.is_empty() && public_http_url(abstract_url) {
        results.push(SearchResult {
            title: value["Heading"]
                .as_str()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or(query)
                .trim()
                .to_owned(),
            url: abstract_url.to_owned(),
            snippet: abstract_text.to_owned(),
            page_excerpt: String::new(),
        });
    }
    collect_related_topics(&value["RelatedTopics"], &mut results, max_results);
    Ok(results)
}

fn collect_related_topics(value: &Value, results: &mut Vec<SearchResult>, max_results: usize) {
    let Some(items) = value.as_array() else {
        return;
    };
    for item in items {
        if results.len() >= max_results {
            return;
        }
        if item["Topics"].is_array() {
            collect_related_topics(&item["Topics"], results, max_results);
            continue;
        }
        let text = item["Text"].as_str().unwrap_or_default().trim();
        let url = item["FirstURL"].as_str().unwrap_or_default().trim();
        if text.is_empty() || !public_http_url(url) {
            continue;
        }
        results.push(SearchResult {
            title: text
                .split(" - ")
                .next()
                .unwrap_or(text)
                .chars()
                .take(80)
                .collect(),
            url: url.to_owned(),
            snippet: text.to_owned(),
            page_excerpt: String::new(),
        });
    }
}

async fn request_public_text(
    source_url: &str,
    max_bytes: usize,
    timeout: Duration,
    cancellation: &CancellationToken,
) -> Result<String, String> {
    request_public_text_with_final_url(source_url, max_bytes, timeout, cancellation)
        .await
        .map(|(_, body)| body)
}

async fn request_public_text_with_final_url(
    source_url: &str,
    max_bytes: usize,
    timeout: Duration,
    cancellation: &CancellationToken,
) -> Result<(String, String), String> {
    let mut current = parse_public_url(source_url).await?;
    for redirect in 0..=MAX_REDIRECTS {
        if cancellation.is_cancelled() {
            return Err("工具调用已取消".to_owned());
        }
        let host = current
            .host_str()
            .ok_or_else(|| "URL 缺少主机名".to_owned())?
            .to_owned();
        let port = current
            .port_or_known_default()
            .ok_or_else(|| "URL 端口无效".to_owned())?;
        let addresses = resolve_public_addresses(&host, port).await?;
        let client = pinned_client(&host, &addresses, timeout)?;
        let request = client
            .get(current.clone())
            .header(
                USER_AGENT,
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            )
            .header(
                ACCEPT,
                "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,application/json;q=0.7,*/*;q=0.4",
            )
            .header(ACCEPT_LANGUAGE, "zh-CN,zh;q=0.9,en;q=0.7")
            .header("accept-encoding", "identity");
        let response = tokio::select! {
            _ = cancellation.cancelled() => return Err("工具调用已取消".to_owned()),
            response = request.send() => response.map_err(|error| format!("请求失败：{error}"))?,
        };
        if response.status().is_redirection() {
            if redirect == MAX_REDIRECTS {
                return Err(format!("重定向次数超过 {MAX_REDIRECTS} 次"));
            }
            let location = response
                .headers()
                .get(LOCATION)
                .and_then(|value| value.to_str().ok())
                .ok_or_else(|| "重定向响应缺少有效 Location".to_owned())?;
            let target = current
                .join(location)
                .map_err(|error| format!("重定向 URL 无效：{error}"))?;
            current = parse_public_url(target.as_str()).await?;
            continue;
        }
        if !response.status().is_success() {
            return Err(format!("远端返回 HTTP {}", response.status()));
        }
        if let Some(length) = response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<usize>().ok())
            && length > max_bytes
        {
            return Err(format!("响应体超过 {} KiB 上限", max_bytes / 1024));
        }
        if let Some(content_type) = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
        {
            let content_type = content_type.to_ascii_lowercase();
            if !["text/", "html", "xml", "json"]
                .iter()
                .any(|token| content_type.contains(token))
            {
                return Err("远端内容不是可读取的文本、HTML、XML 或 JSON".to_owned());
            }
        }
        let mut response = response;
        let mut bytes = Vec::with_capacity(max_bytes.min(64 * 1024));
        loop {
            let chunk = tokio::select! {
                _ = cancellation.cancelled() => return Err("工具调用已取消".to_owned()),
                chunk = response.chunk() => chunk.map_err(|error| format!("读取响应失败：{error}"))?,
            };
            let Some(chunk) = chunk else {
                break;
            };
            if bytes.len().saturating_add(chunk.len()) > max_bytes {
                return Err(format!("响应体超过 {} KiB 上限", max_bytes / 1024));
            }
            bytes.extend_from_slice(&chunk);
        }
        return Ok((
            current.to_string(),
            String::from_utf8_lossy(&bytes).into_owned(),
        ));
    }
    unreachable!("bounded redirect loop always returns")
}

async fn parse_public_url(source: &str) -> Result<Url, String> {
    if source.len() > 4096 || source.chars().any(char::is_control) {
        return Err("URL 过长或包含控制字符".to_owned());
    }
    let url = Url::parse(source).map_err(|_| "url 必须是完整的 http/https 链接".to_owned())?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err("url 必须是完整的 http/https 链接".to_owned());
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("URL 不允许包含用户名或密码".to_owned());
    }
    let host = url.host_str().expect("validated URL host");
    let port = url
        .port_or_known_default()
        .ok_or_else(|| "URL 端口无效".to_owned())?;
    resolve_public_addresses(host, port).await?;
    Ok(url)
}

async fn resolve_public_addresses(host: &str, port: u16) -> Result<Vec<SocketAddr>, String> {
    let addresses = lookup_host((host, port))
        .await
        .map_err(|error| format!("无法解析主机 {host}：{error}"))?
        .collect::<HashSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    if addresses.is_empty() || addresses.iter().any(|address| !is_public_ip(address.ip())) {
        return Err("URL 解析到私有、保留或非公网地址，已阻止访问".to_owned());
    }
    Ok(addresses)
}

fn pinned_client(
    host: &str,
    addresses: &[SocketAddr],
    timeout: Duration,
) -> Result<Client, String> {
    Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .timeout(timeout)
        .resolve_to_addrs(host, addresses)
        .build()
        .map_err(|error| format!("无法建立受限 HTTP 客户端：{error}"))
}

fn is_public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => is_public_ipv4(ip),
        IpAddr::V6(ip) => is_public_ipv6(ip),
    }
}

fn is_public_ipv4(ip: Ipv4Addr) -> bool {
    let octets = ip.octets();
    !(ip.is_unspecified()
        || ip.is_private()
        || ip.is_loopback()
        || ip.is_link_local()
        || ip.is_multicast()
        || ip.is_broadcast()
        || octets[0] == 0
        || octets[0] >= 240
        || (octets[0] == 100 && (64..=127).contains(&octets[1]))
        || (octets[0] == 192 && octets[1] == 0 && octets[2] == 0)
        || (octets[0] == 192 && octets[1] == 0 && octets[2] == 2)
        || (octets[0] == 198 && (octets[1] == 18 || octets[1] == 19))
        || (octets[0] == 198 && octets[1] == 51 && octets[2] == 100)
        || (octets[0] == 203 && octets[1] == 0 && octets[2] == 113))
}

fn is_public_ipv6(ip: Ipv6Addr) -> bool {
    if let Some(ipv4) = ip.to_ipv4_mapped() {
        return is_public_ipv4(ipv4);
    }
    let segments = ip.segments();
    let in_global_unicast = (segments[0] & 0xe000) == 0x2000;
    let documentation = segments[0] == 0x2001 && segments[1] == 0x0db8;
    in_global_unicast
        && !documentation
        && !ip.is_unspecified()
        && !ip.is_loopback()
        && !ip.is_multicast()
}

fn parse_bing_results(html: &str, max_results: usize) -> Vec<SearchResult> {
    parse_result_blocks(html, "<li", "b_algo", "</li>", max_results, |block| {
        anchor_in_block(block, Some("<h2"))
    })
}

fn parse_duckduckgo_results(html: &str, max_results: usize) -> Vec<SearchResult> {
    parse_anchors(html)
        .into_iter()
        .filter(|(attributes, _, _)| attributes.contains("result__a"))
        .filter_map(|(_, url, title)| search_result(title, clean_redirect_url(&url), String::new()))
        .take(max_results)
        .collect()
}

fn parse_google_results(html: &str, max_results: usize) -> Vec<SearchResult> {
    parse_anchors(html)
        .into_iter()
        .filter(|(_, url, title)| {
            !title.is_empty() && (url.starts_with("/url?") || public_http_url(url))
        })
        .filter_map(|(_, url, title)| search_result(title, clean_redirect_url(&url), String::new()))
        .take(max_results)
        .collect()
}

fn parse_baidu_results(html: &str, max_results: usize) -> Vec<SearchResult> {
    parse_result_blocks(html, "<h3", "", "</h3>", max_results, |block| {
        anchor_in_block(block, None)
    })
}

fn parse_result_blocks<F>(
    html: &str,
    start_tag: &str,
    required_attribute: &str,
    end_tag: &str,
    max_results: usize,
    mut anchor: F,
) -> Vec<SearchResult>
where
    F: FnMut(&str) -> Option<(String, String)>,
{
    let lower = html.to_ascii_lowercase();
    let required = required_attribute.to_ascii_lowercase();
    let mut cursor = 0;
    let mut results = Vec::new();
    while results.len() < max_results {
        let Some(relative_start) = lower[cursor..].find(start_tag) else {
            break;
        };
        let start = cursor + relative_start;
        let Some(open_end_relative) = lower[start..].find('>') else {
            break;
        };
        let open_end = start + open_end_relative + 1;
        if !required.is_empty() && !lower[start..open_end].contains(&required) {
            cursor = open_end;
            continue;
        }
        let Some(end_relative) = lower[open_end..].find(end_tag) else {
            break;
        };
        let end = open_end + end_relative + end_tag.len();
        if let Some((url, title)) = anchor(&html[start..end])
            && let Some(result) = search_result(title, clean_redirect_url(&url), String::new())
        {
            results.push(result);
        }
        cursor = end;
    }
    results
}

fn anchor_in_block(block: &str, after_marker: Option<&str>) -> Option<(String, String)> {
    let source = if let Some(marker) = after_marker {
        let lower = block.to_ascii_lowercase();
        let index = lower.find(marker)?;
        &block[index..]
    } else {
        block
    };
    parse_anchors(source)
        .into_iter()
        .next()
        .map(|(_, url, title)| (url, title))
}

fn parse_anchors(html: &str) -> Vec<(String, String, String)> {
    let lower = html.to_ascii_lowercase();
    let mut cursor = 0;
    let mut anchors = Vec::new();
    while let Some(relative_start) = lower[cursor..].find("<a") {
        let start = cursor + relative_start;
        let Some(open_end_relative) = lower[start..].find('>') else {
            break;
        };
        let open_end = start + open_end_relative;
        let attributes = &html[start + 2..open_end];
        let Some(close_relative) = lower[open_end + 1..].find("</a>") else {
            break;
        };
        let close = open_end + 1 + close_relative;
        if let Some(href) = html_attribute(attributes, "href") {
            anchors.push((
                attributes.to_ascii_lowercase(),
                decode_html_entities(&href),
                readable_text(&html[open_end + 1..close], 200),
            ));
        }
        cursor = close + 4;
    }
    anchors
}

fn html_attribute(attributes: &str, key: &str) -> Option<String> {
    let bytes = attributes.as_bytes();
    let lower = attributes.to_ascii_lowercase();
    let lower_bytes = lower.as_bytes();
    let key = key.as_bytes();
    let mut index = 0;
    while index + key.len() <= bytes.len() {
        if &lower_bytes[index..index + key.len()] == key
            && (index == 0 || !is_attr_char(bytes[index - 1]))
            && (index + key.len() == bytes.len() || !is_attr_char(bytes[index + key.len()]))
        {
            let mut cursor = index + key.len();
            while cursor < bytes.len() && bytes[cursor].is_ascii_whitespace() {
                cursor += 1;
            }
            if bytes.get(cursor) != Some(&b'=') {
                index += key.len();
                continue;
            }
            cursor += 1;
            while cursor < bytes.len() && bytes[cursor].is_ascii_whitespace() {
                cursor += 1;
            }
            let quote = *bytes.get(cursor)?;
            if quote == b'\'' || quote == b'"' {
                cursor += 1;
                let end = bytes[cursor..].iter().position(|value| *value == quote)? + cursor;
                return Some(attributes[cursor..end].to_owned());
            }
            let end = bytes[cursor..]
                .iter()
                .position(|value| value.is_ascii_whitespace())
                .map(|value| cursor + value)
                .unwrap_or(bytes.len());
            return Some(attributes[cursor..end].to_owned());
        }
        index += 1;
    }
    None
}

fn is_attr_char(value: u8) -> bool {
    value.is_ascii_alphanumeric() || matches!(value, b'_' | b'-' | b':')
}

fn search_result(title: String, url: String, snippet: String) -> Option<SearchResult> {
    let title = normalize_space(&title);
    if title.is_empty() || !public_http_url(&url) {
        return None;
    }
    Some(SearchResult {
        title,
        url,
        snippet: normalize_space(&snippet),
        page_excerpt: String::new(),
    })
}

fn clean_redirect_url(raw_url: &str) -> String {
    let mut link = decode_html_entities(raw_url).trim().to_owned();
    if link.starts_with("//") {
        link.insert_str(0, "https:");
    } else if link.starts_with("/url?") {
        link.insert_str(0, "https://www.google.com");
    }
    let Ok(parsed) = Url::parse(&link) else {
        return link;
    };
    let host = parsed.host_str().unwrap_or_default().to_ascii_lowercase();
    if host.ends_with("duckduckgo.com") && parsed.path().starts_with("/l/") {
        if let Some((_, target)) = parsed.query_pairs().find(|(key, _)| key == "uddg") {
            return target.into_owned();
        }
    }
    if host.ends_with("google.com") && parsed.path() == "/url" {
        if let Some((_, target)) = parsed.query_pairs().find(|(key, _)| key == "q") {
            return target.into_owned();
        }
    }
    link
}

fn public_http_url(value: &str) -> bool {
    Url::parse(value)
        .map(|url| {
            matches!(url.scheme(), "http" | "https")
                && url.host_str().is_some()
                && url.username().is_empty()
                && url.password().is_none()
        })
        .unwrap_or(false)
}

fn html_title(html: &str) -> Option<String> {
    let lower = html.to_ascii_lowercase();
    let start = lower.find("<title")?;
    let open_end = lower[start..].find('>')? + start + 1;
    let close = lower[open_end..].find("</title>")? + open_end;
    let title = readable_text(&html[open_end..close], 120);
    (!title.is_empty()).then_some(title)
}

fn readable_text(html: &str, max_chars: usize) -> String {
    let mut output = String::new();
    let mut tag = String::new();
    let mut in_tag = false;
    let mut skip_depth = 0usize;
    for character in html.chars() {
        if in_tag {
            if character == '>' {
                let normalized = tag.trim().to_ascii_lowercase();
                let name = normalized
                    .trim_start_matches('/')
                    .split_ascii_whitespace()
                    .next()
                    .unwrap_or_default()
                    .trim_end_matches('/');
                let closing = normalized.starts_with('/');
                if matches!(
                    name,
                    "script" | "style" | "noscript" | "svg" | "canvas" | "template"
                ) {
                    if closing {
                        skip_depth = skip_depth.saturating_sub(1);
                    } else if !normalized.ends_with('/') {
                        skip_depth = skip_depth.saturating_add(1);
                    }
                } else if skip_depth == 0
                    && matches!(
                        name,
                        "br" | "p" | "div" | "li" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6" | "tr"
                    )
                {
                    output.push('\n');
                }
                tag.clear();
                in_tag = false;
            } else if tag.len() < 1024 {
                tag.push(character);
            }
            continue;
        }
        if character == '<' {
            in_tag = true;
        } else if skip_depth == 0 {
            output.push(character);
        }
    }
    let decoded = decode_html_entities(&output);
    normalize_text_lines(&decoded, max_chars)
}

fn decode_html_entities(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    let mut remaining = value;
    while let Some(index) = remaining.find('&') {
        output.push_str(&remaining[..index]);
        remaining = &remaining[index..];
        let Some(end) = remaining.find(';').filter(|end| *end <= 12) else {
            output.push('&');
            remaining = &remaining[1..];
            continue;
        };
        let entity = &remaining[1..end];
        let decoded = match entity {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" | "#39" => Some('\''),
            "nbsp" => Some(' '),
            _ if entity.starts_with("#x") || entity.starts_with("#X") => {
                u32::from_str_radix(&entity[2..], 16)
                    .ok()
                    .and_then(char::from_u32)
            }
            _ if entity.starts_with('#') => entity[1..].parse().ok().and_then(char::from_u32),
            _ => None,
        };
        if let Some(decoded) = decoded {
            output.push(decoded);
        } else {
            output.push_str(&remaining[..=end]);
        }
        remaining = &remaining[end + 1..];
    }
    output.push_str(remaining);
    output
}

fn normalize_text_lines(value: &str, max_chars: usize) -> String {
    let mut output = String::new();
    for line in value.lines() {
        let line = normalize_space(line);
        if line.is_empty() {
            continue;
        }
        if !output.is_empty() {
            output.push('\n');
        }
        output.push_str(&line);
        if output.chars().count() >= max_chars {
            break;
        }
    }
    output
        .chars()
        .take(max_chars)
        .collect::<String>()
        .trim()
        .to_owned()
}

fn normalize_space(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn form_encode(values: &[(&str, &str)]) -> String {
    url::form_urlencoded::Serializer::new(String::new())
        .extend_pairs(values.iter().copied())
        .finish()
}

fn format_search_results(
    query: &str,
    results: &[SearchResult],
    engine: WebSearchEngine,
    now: LocalDateTime,
) -> String {
    let mut lines = vec![
        format!("查询：{query}"),
        format!("搜索引擎：{}", engine.label()),
        format!("检索时间：{}", now.isoformat().replace('T', " ")),
    ];
    for (index, result) in results.iter().enumerate() {
        lines.push(format!(
            "{}. {}\n   URL: {}\n   摘要：{}",
            index + 1,
            result.title,
            result.url,
            result.snippet
        ));
        if !result.page_excerpt.is_empty() {
            lines.push(format!("   正文摘录：{}", result.page_excerpt));
        }
    }
    lines.join("\n")
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn config_bool(config: &ConfigDocument, key: &str, default: bool) -> bool {
    config.get(key).and_then(Value::as_bool).unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn web_settings_normalize_python_compatible_defaults() {
        let mut config = ConfigDocument::default();
        config.set("llm_web_search_enabled", Value::Bool(true));
        config.set("llm_web_search_engine", Value::String("google".to_owned()));
        config.set("llm_web_search_show_sources", Value::Bool(false));
        config.set("llm_web_fetch_enabled", Value::Bool(true));
        let settings = NativeWebToolSettings::from_config(&config);
        assert!(settings.search_enabled);
        assert_eq!(settings.search_engine, WebSearchEngine::Google);
        assert!(!settings.show_sources);
        assert!(settings.fetch_enabled);
        assert_eq!(
            WebSearchEngine::parse("unsupported"),
            WebSearchEngine::BingCn
        );
    }

    #[test]
    fn private_reserved_and_documentation_addresses_are_blocked() {
        for address in [
            "127.0.0.1",
            "10.0.0.1",
            "169.254.1.1",
            "100.64.0.1",
            "192.0.2.1",
            "198.51.100.4",
            "203.0.113.9",
            "::1",
            "fc00::1",
            "fe80::1",
            "2001:db8::1",
        ] {
            assert!(!is_public_ip(address.parse().unwrap()), "{address}");
        }
        assert!(is_public_ip("8.8.8.8".parse().unwrap()));
        assert!(is_public_ip("2606:4700:4700::1111".parse().unwrap()));
    }

    #[test]
    fn html_extractors_remove_active_content_and_decode_entities() {
        let html = "<html><head><title>A &amp; B</title><style>hidden</style></head><body><h1>Hello</h1><script>bad()</script><p>世界&nbsp;test</p></body></html>";
        assert_eq!(html_title(html).as_deref(), Some("A & B"));
        let body = readable_text(html, 200);
        assert!(body.contains("Hello"));
        assert!(body.contains("世界 test"));
        assert!(!body.contains("hidden"));
        assert!(!body.contains("bad()"));
    }

    #[test]
    fn search_result_parsers_keep_public_links_and_clean_redirects() {
        let bing = r#"<li class="b_algo"><h2><a href="https://example.com/a">Alpha</a></h2><p>One</p></li>"#;
        let duck = r#"<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb">Beta</a>"#;
        let google = r#"<a href="/url?q=https%3A%2F%2Fexample.net%2Fc"><h3>Gamma</h3></a>"#;
        assert_eq!(parse_bing_results(bing, 5)[0].title, "Alpha");
        assert_eq!(
            parse_duckduckgo_results(duck, 5)[0].url,
            "https://example.org/b"
        );
        assert_eq!(parse_google_results(google, 5)[0].title, "Gamma");
    }

    #[tokio::test]
    async fn fetch_rejects_credentials_and_non_http_schemes_before_network_access() {
        let cancellation = CancellationToken::new();
        assert!(parse_public_url("file:///etc/passwd").await.is_err());
        assert!(
            parse_public_url("http://user:pass@example.com/")
                .await
                .is_err()
        );
        let result = web_fetch(
            "http://127.0.0.1/private",
            6000,
            LocalDateTime::parse("2026-07-15T12:00:00").unwrap(),
            &cancellation,
        )
        .await;
        assert!(result.unwrap_err().contains("私有"));
    }

    #[test]
    fn cancelled_result_formatting_is_bounded() {
        let result = SearchResult {
            title: "Title".to_owned(),
            url: "https://example.com".to_owned(),
            snippet: "Snippet".to_owned(),
            page_excerpt: "Excerpt".to_owned(),
        };
        let text = format_search_results(
            "query",
            &[result],
            WebSearchEngine::BingCn,
            LocalDateTime::parse("2026-07-15T12:00:00").unwrap(),
        );
        assert!(text.contains("搜索引擎：Bing CN"));
        assert!(text.contains("检索时间：2026-07-15 12:00:00"));
    }
}
