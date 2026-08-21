#!/usr/bin/env python3
"""Minimal fail-closed CONNECT proxy for the efficacy-v2 Codex sandbox."""

from __future__ import annotations

import select
import socket
import socketserver
import sys

ALLOWED_HOSTS = ("chatgpt.com", "auth.openai.com", "api.openai.com")
MAX_HEADER_BYTES = 16_384


def allowed(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    return any(normalized == item or normalized.endswith("." + item) for item in ALLOWED_HOSTS)


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(15)
        data = bytearray()
        while b"\r\n\r\n" not in data and len(data) < MAX_HEADER_BYTES:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data.extend(chunk)
        try:
            first = bytes(data).split(b"\r\n", 1)[0].decode("ascii")
            method, authority, _version = first.split(" ", 2)
            host, port_text = authority.rsplit(":", 1)
            port = int(port_text)
        except (ValueError, UnicodeDecodeError):
            self.request.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            return
        if method != "CONNECT" or port != 443 or not allowed(host):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            print(f"DENY {method} {host}:{port}", flush=True)
            return
        try:
            upstream = socket.create_connection((host, port), timeout=15)
        except OSError as exc:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            print(f"UPSTREAM_ERROR {host}:{port} {type(exc).__name__}", flush=True)
            return
        print(f"ALLOW CONNECT {host}:{port}", flush=True)
        with upstream:
            upstream.setblocking(False)
            self.request.setblocking(False)
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            sockets = (self.request, upstream)
            while True:
                readable, _, exceptional = select.select(sockets, (), sockets, 30)
                if exceptional or not readable:
                    return
                for source in readable:
                    try:
                        payload = source.recv(65_536)
                    except OSError:
                        return
                    if not payload:
                        return
                    target = upstream if source is self.request else self.request
                    try:
                        target.sendall(payload)
                    except OSError:
                        return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 8080), Handler) as server:
        print("READY codex-egress-proxy 0.0.0.0:8080", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            sys.exit(0)
