from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, getproxies, urlopen


@dataclass(frozen=True)
class ParsedProxy:
    url: str
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""


def normalize_proxy_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value


def effective_proxy_url(
    proxy_url: str = "",
    use_system_proxy: bool = True,
    purpose: str = "generic",
) -> str:
    custom = normalize_proxy_url(proxy_url)
    if custom:
        return custom
    if not use_system_proxy:
        return ""
    proxies = getproxies()
    if purpose == "telegram":
        keys = ("all", "socks", "https", "http")
    elif purpose == "http":
        keys = ("https", "http", "all", "socks")
    else:
        keys = ("all", "https", "http", "socks")
    for key in keys:
        candidate = proxies.get(key)
        if candidate:
            return normalize_proxy_url(candidate)
    return ""


def parse_proxy_url(
    proxy_url: str = "",
    use_system_proxy: bool = True,
    purpose: str = "generic",
) -> ParsedProxy | None:
    url = effective_proxy_url(proxy_url, use_system_proxy, purpose)
    if not url:
        return None
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https", "socks4", "socks5", "socks5h"}:
        raise ValueError(f"不支持的代理协议：{scheme}")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    default_port = 8080 if scheme in {"http", "https"} else 1080
    return ParsedProxy(
        url=url,
        scheme=scheme,
        host=parsed.hostname,
        port=int(parsed.port or default_port),
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
    )


def telethon_proxy(proxy_url: str = "", use_system_proxy: bool = True) -> tuple | None:
    proxy = parse_proxy_url(proxy_url, use_system_proxy, "telegram")
    if proxy is None:
        return None
    try:
        import python_socks  # noqa: F401
    except ImportError:
        try:
            import socks  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "已配置网络代理，但缺少 python-socks 依赖，请重新安装 requirements.txt"
            ) from exc
    proxy_type = "http" if proxy.scheme in {"http", "https"} else proxy.scheme.replace("socks5h", "socks5")
    return (
        proxy_type,
        proxy.host,
        proxy.port,
        True,
        proxy.username or None,
        proxy.password or None,
    )


def urllib_proxy_map(proxy_url: str = "", use_system_proxy: bool = True) -> dict[str, str]:
    proxy = parse_proxy_url(proxy_url, use_system_proxy, "http")
    if proxy is None:
        return {}
    if proxy.scheme not in {"http", "https"}:
        # urllib does not support SOCKS by itself. Telegram can still use SOCKS
        # through python-socks; HTTP requests should use an HTTP/mixed proxy port.
        return {}
    return {"http": proxy.url, "https": proxy.url}


def proxy_label(
    proxy_url: str = "",
    use_system_proxy: bool = True,
    purpose: str = "generic",
) -> str:
    proxy = parse_proxy_url(proxy_url, use_system_proxy, purpose)
    if proxy is None:
        return "未使用代理"
    auth = "（带认证）" if proxy.username else ""
    return f"{proxy.scheme}://{proxy.host}:{proxy.port}{auth}"


def yande_proxy_warning(proxy_url: str = "", use_system_proxy: bool = True) -> str:
    proxy = parse_proxy_url(proxy_url, use_system_proxy, "http")
    if proxy is None or proxy.scheme in {"http", "https"}:
        return ""
    return "Yande 当前使用 HTTP 下载器，SOCKS 代理不会生效；请填写 HTTP/mixed 代理端口。"


def _test_socket(host: str, port: int, timeout: float = 5.0) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        return


def _test_yande_http(proxy_url: str = "", use_system_proxy: bool = True) -> tuple[bool, str]:
    warning = yande_proxy_warning(proxy_url, use_system_proxy)
    if warning:
        return False, warning
    proxy_map = urllib_proxy_map(proxy_url, use_system_proxy)
    request = Request(
        "https://yande.re/post.json?limit=1",
        headers={
            "User-Agent": "TG-Pic-Collector/1.0",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    try:
        if proxy_map:
            opener = build_opener(ProxyHandler(proxy_map), HTTPSHandler(context=ssl.create_default_context()))
            with opener.open(request, timeout=8) as response:
                response.read(32)
        else:
            with urlopen(request, timeout=8) as response:
                response.read(32)
        return True, f"Yande HTTP 请求成功（{proxy_label(proxy_url, use_system_proxy, 'http')}）"
    except HTTPError as exc:
        return False, f"Yande 请求返回 HTTP {exc.code}"
    except (URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"Yande 请求失败：{reason}"


def run_network_diagnostics(proxy_url: str = "", use_system_proxy: bool = True) -> tuple[bool, str]:
    parts: list[str] = []
    ok = True

    try:
        proxy = parse_proxy_url(proxy_url, use_system_proxy, "telegram")
        if proxy:
            telethon_proxy(proxy_url, use_system_proxy)
            _test_socket(proxy.host, proxy.port)
            parts.append(f"Telegram 代理端口可连接：{proxy_label(proxy_url, use_system_proxy, 'telegram')}")
        else:
            _test_socket("149.154.167.50", 443)
            parts.append("Telegram 直连测试成功")
    except Exception as exc:
        ok = False
        parts.append(f"Telegram 网络测试失败：{exc}")

    yande_ok, yande_message = _test_yande_http(proxy_url, use_system_proxy)
    ok = ok and yande_ok
    parts.append(yande_message)
    return ok, "\n".join(parts)
