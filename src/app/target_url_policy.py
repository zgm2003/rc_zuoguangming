from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

BLOCKED_HOSTNAMES = {"localhost"}


def validate_target_url_allowed(target_url: str) -> str:
    parsed = urlsplit(target_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("target_url must use http or https")
    if not parsed.hostname:
        raise ValueError("target_url must include a hostname")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise ValueError("target_url is not allowed")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return target_url

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ValueError("target_url is not allowed")
    return target_url
