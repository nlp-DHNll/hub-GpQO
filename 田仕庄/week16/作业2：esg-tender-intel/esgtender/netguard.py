"""出站地址闸门：只放行公网 http(s)，挡住 SSRF 与「公网跳内网」。

为什么需要
----------
``crawl`` 的 ``list_url`` 来自 ``config/sources.yaml``，``notify`` 的 URL 来自
环境变量，两者都能被「改一个配置」这一动作指向内网。httpx 默认不做任何过滤，
``follow_redirects=True`` 时还会把公网 URL 跳到 127.0.0.1——校验必须发生在
**每一跳**，只校验入口等于没校验（入口是公网、重定向到元数据地址，是最常见的
SSRF 绕过手法）。

残余风险
--------
``assert_public_url`` 与真正 ``connect`` 之间仍有 DNS rebinding 的 TOCTOU 窗口。
对本 skill 的威胁模型（本地 CLI、配置由使用者维护），逐跳校验已经能挡住
「顺手改个 URL」这类误用；要彻底关掉需把解析结果钉死在传输层，代价不值得。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# 不区分 IPv4/IPv6：匹配时按版本挑
_BLOCKED_NETS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",     # 运营商级 NAT，云厂商内网也常落这里
        "127.0.0.0/8",
        "169.254.0.0/16",    # 链路本地：云实例元数据 169.254.169.254
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "64:ff9b::/96",      # NAT64，可把内网 v4 映射成 v6
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)

ALLOWED_SCHEMES = ("http", "https")


class BlockedAddress(ValueError):
    """目标地址不允许访问（内网、环回、非 http(s)、解析失败）。"""


def _is_public(ip_text: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped  # ::ffff:127.0.0.1 必须按 v4 判
    return not any(addr in net for net in _BLOCKED_NETS if net.version == addr.version)


def _resolve(host: str, port: int) -> list[str]:
    """解析域名，返回全部 IP。单独成函数便于测试里替换（不想让单测依赖 DNS）。"""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def assert_public_url(url: str) -> str:
    """校验 URL 是否指向公网；不通过抛 ``BlockedAddress``，通过返回原 URL。"""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedAddress(f"仅允许 http(s)，收到 {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise BlockedAddress("URL 缺少主机名")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:  # :99999 或 :abc —— urlparse 会抛裸 ValueError
        raise BlockedAddress(f"URL 端口非法：{exc}") from exc
    try:
        addresses = _resolve(host, port)
    except socket.gaierror as exc:
        raise BlockedAddress(f"域名无法解析：{host}") from exc
    if not addresses:
        raise BlockedAddress(f"域名无解析结果：{host}")
    for address in addresses:  # 一个域名可能解析出多个 A/AAAA，任一在内网就拒绝
        if not _is_public(address):
            raise BlockedAddress(f"{host} 解析到非公网地址 {address}")
    return url


def safe_get(
    url: str,
    *,
    timeout: float = 15.0,
    max_hops: int = 3,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """手动跟随重定向的 GET，每一跳都过 ``assert_public_url``。"""
    for _ in range(max_hops + 1):
        assert_public_url(url)
        response = httpx.get(url, timeout=timeout, follow_redirects=False, headers=headers)
        location = response.headers.get("location")
        if response.is_redirect and location:
            url = str(response.url.join(location))
            continue
        response.raise_for_status()
        return response
    raise BlockedAddress(f"重定向超过 {max_hops} 跳：{url}")
