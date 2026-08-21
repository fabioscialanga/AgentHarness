#!/usr/bin/env python3
"""Deterministic network-policy probe for the efficacy-v2 agent network."""

from __future__ import annotations

import socket

PROXY = ("egress-proxy", 8080)


def connect_status(host: str) -> bytes:
    with socket.create_connection(PROXY, timeout=10) as stream:
        stream.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode("ascii"))
        response = stream.recv(256)
    return response.split(b"\r\n", 1)[0]


allowed = connect_status("chatgpt.com")
denied = connect_status("raw.githubusercontent.com")
if b" 200 " not in allowed:
    raise SystemExit(f"provider CONNECT unavailable: {allowed!r}")
if b" 403 " not in denied:
    raise SystemExit(f"heldout host was not denied: {denied!r}")

try:
    socket.create_connection(("raw.githubusercontent.com", 443), timeout=3).close()
except OSError:
    direct_blocked = True
else:
    direct_blocked = False
if not direct_blocked:
    raise SystemExit("direct Internet bypass unexpectedly reachable")

print("EGRESS_POLICY_OK provider_connect=200 heldout_connect=403 direct_bypass=blocked")
