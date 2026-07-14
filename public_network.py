from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Mapping


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass(frozen=True)
class _ResolvedEndpoint:
    family: int
    socket_type: int
    protocol: int
    address: tuple


@dataclass(frozen=True)
class _ParsedPublicUrl:
    scheme: str
    host: str
    port: int
    request_target: str


class PublicHttpResponse:
    """HTTP response whose close also tears down its pinned connection."""

    def __init__(
        self,
        response: http.client.HTTPResponse,
        connection: http.client.HTTPConnection,
        url: str,
    ) -> None:
        self._response = response
        self._connection = connection
        self.url = url
        self.headers = response.headers
        self.status = response.status
        self.reason = response.reason
        self._closed = False

    def read(self, amount: int | None = None) -> bytes:
        if amount is None:
            return self._response.read()
        return self._response.read(amount)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._response.close()
        finally:
            self._connection.close()

    def __enter__(self) -> PublicHttpResponse:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _parse_public_url(url: str) -> _ParsedPublicUrl:
    text = str(url or "").strip()
    if not text or any(character in text for character in ("\r", "\n", "\x00")):
        raise ValueError("Invalid remote image URL")

    parsed = urllib.parse.urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS image URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials are not allowed in remote image URLs")

    host = parsed.hostname
    if not host:
        raise ValueError("Remote image URL has no host")
    try:
        ascii_host = host.encode("idna").decode("ascii")
        explicit_port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Remote image URL has an invalid host or port") from exc
    port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
    if port < 1:
        raise ValueError("Remote image URL has an invalid port")

    path = urllib.parse.quote(
        parsed.path or "/",
        safe="/%:@!$&'()*+,;=-._~",
    )
    query = urllib.parse.quote(
        parsed.query,
        safe="=&?/:;+,%@!$'()*[]-._~",
    )
    request_target = path + (f"?{query}" if query else "")
    return _ParsedPublicUrl(scheme, ascii_host, port, request_target)


def _resolve_public_endpoints(host: str, port: int) -> tuple[_ResolvedEndpoint, ...]:
    try:
        records = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise OSError(f"Could not resolve remote image host: {host}") from exc

    endpoints: list[_ResolvedEndpoint] = []
    seen: set[tuple[int, tuple]] = set()
    for family, socket_type, protocol, _canonical_name, address in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        try:
            resolved_ip = ipaddress.ip_address(address[0].split("%", 1)[0])
        except ValueError as exc:
            raise PermissionError("Remote image host resolved to an invalid address") from exc
        if not resolved_ip.is_global or resolved_ip.is_multicast:
            raise PermissionError(
                "Remote image URLs may only resolve to public Internet addresses"
            )
        key = (family, address)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(_ResolvedEndpoint(family, socket_type, protocol, address))

    if not endpoints:
        raise OSError(f"Remote image host has no usable Internet address: {host}")
    return tuple(endpoints)


def _connect_endpoint(endpoint: _ResolvedEndpoint, timeout: float) -> socket.socket:
    connection = socket.socket(
        endpoint.family,
        endpoint.socket_type,
        endpoint.protocol,
    )
    try:
        connection.settimeout(timeout)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.connect(endpoint.address)
        return connection
    except BaseException:
        connection.close()
        raise


class _PinnedHttpConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, endpoint: _ResolvedEndpoint, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self._endpoint = endpoint

    def connect(self) -> None:
        self.sock = _connect_endpoint(self._endpoint, self.timeout)


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        endpoint: _ResolvedEndpoint,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._endpoint = endpoint

    def connect(self) -> None:
        raw_socket = _connect_endpoint(self._endpoint, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except BaseException:
            raw_socket.close()
            raise


def _create_connection(
    parsed: _ParsedPublicUrl,
    endpoint: _ResolvedEndpoint,
    timeout: float,
    tls_context: ssl.SSLContext,
) -> http.client.HTTPConnection:
    if parsed.scheme == "https":
        return _PinnedHttpsConnection(
            parsed.host,
            parsed.port,
            endpoint,
            timeout,
            tls_context,
        )
    return _PinnedHttpConnection(parsed.host, parsed.port, endpoint, timeout)


def open_public_url(
    url: str,
    *,
    timeout: float = 12,
    max_redirects: int = 5,
    headers: Mapping[str, str] | None = None,
) -> tuple[PublicHttpResponse, str]:
    """Open a URL through a socket pinned to its validated public IP address."""

    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    if max_redirects < 0:
        raise ValueError("Maximum redirects cannot be negative")

    current_url = str(url or "").strip()
    request_headers = {
        "User-Agent": "BanG-Dream-Desktop-Pet/1.0",
        "Accept": "image/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if headers:
        request_headers.update({str(key): str(value) for key, value in headers.items()})
    tls_context = ssl.create_default_context()

    for redirect_count in range(max_redirects + 1):
        parsed = _parse_public_url(current_url)
        endpoints = _resolve_public_endpoints(parsed.host, parsed.port)
        last_error: BaseException | None = None

        for endpoint in endpoints:
            connection = _create_connection(parsed, endpoint, timeout, tls_context)
            try:
                connection.request("GET", parsed.request_target, headers=request_headers)
                raw_response = connection.getresponse()
                response = PublicHttpResponse(raw_response, connection, current_url)
            except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
                connection.close()
                last_error = exc
                continue

            if response.status in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise OSError("Remote image redirect did not include a destination")
                if redirect_count >= max_redirects:
                    raise OSError("Remote image URL redirected too many times")
                current_url = urllib.parse.urljoin(current_url, location)
                break

            if response.status >= 400:
                status = response.status
                response.close()
                raise OSError(f"Remote image request failed with HTTP {status}")
            return response, current_url
        else:
            if last_error is not None:
                raise OSError("Could not connect to the remote image host") from last_error
            raise OSError("Remote image host has no reachable Internet address")

        # A redirect breaks out of the endpoint loop and is validated on the next pass.
        continue

    raise OSError("Remote image URL redirected too many times")
