"""Synthetic child executable used only by offline supervisor tests."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data import refresh_worker as worker
from app.data.refresh_protocol import encode, receive

scenario = sys.argv[1]


def forbidden(*args, **kwargs):
    raise AssertionError("Worker must not access SQLite or the network")


sqlite3.connect = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
assert "SIFTING_API_KEY" not in os.environ

if scenario in {"malformed", "truncated", "oversized", "mismatch", "crash", "duplicate_key", "cursor_injection"}:
    first = receive(sys.stdin.buffer)
    if scenario == "crash":
        os._exit(7)
    if scenario == "cursor_injection":
        sys.stdout.buffer.write(encode(dict(v=1, type="admit", attempt=first["attempt"], index=0, cursor="forged")))
    elif scenario == "oversized":
        sys.stdout.buffer.write(struct.pack("!I", 4_000_001))
    elif scenario == "truncated":
        sys.stdout.buffer.write(struct.pack("!I", 100) + b"{")
    elif scenario == "malformed":
        sys.stdout.buffer.write(struct.pack("!I", 1) + b"{")
    elif scenario == "duplicate_key":
        body = b'{"v":1,"v":1}'
        sys.stdout.buffer.write(struct.pack("!I", len(body)) + body)
    else:
        sys.stdout.buffer.write(encode(dict(v=1, type="complete", attempt="wrong", pages=1)))
    sys.stdout.buffer.flush()
    sys.exit(0)

if scenario == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

if scenario == "dns":
    def blocked_dns(*args, **kwargs):
        time.sleep(60)
        raise AssertionError("DNS simulation must be terminated")
    socket.getaddrinfo = blocked_dns

if scenario in {"missing_terminal", "trailing"}:
    original_encode = worker.encode
    def terminal_encode(message):
        if message["type"] == "complete":
            return b"" if scenario == "missing_terminal" else original_encode(message) * 2
        return original_encode(message)
    worker.encode = terminal_encode

calls = 0


def transport(request, timeout):
    global calls
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(request.full_url).query)
    assert request.get_header("X-api-key") == "synthetic-worker-credential"
    if scenario == "credential_error":
        raise OSError("synthetic secret: " + request.get_header("X-api-key"))
    if scenario in {"slow", "ignore_term"}:
        time.sleep(60)
    if scenario == "multi_timeout":
        time.sleep(1.3)
    start = datetime.fromisoformat(query["start"][0].replace("Z", "+00:00"))
    interval = query["interval"][0]
    step = {"1h": timedelta(hours=1), "15m": timedelta(minutes=15), "1d": timedelta(days=1)}[interval]
    count = int(query["limit"][0]) if scenario == "full_pipe" else 1
    index = calls
    calls += 1
    rows = [dict(t=int((start + step * (index * count + i)).timestamp() * 1000),
                 o="2000", h="2002", l="1999", c="2001", v=1000) for i in range(count)]
    cursor = "next" if scenario in {"two_pages", "multi_timeout", "overlap", "repeated"} and index == 0 else None
    if scenario == "repeated" and index == 1:
        cursor = "next"
    if scenario == "overlap" and index == 1:
        rows[0]["t"] = int(start.timestamp() * 1000)
    if scenario == "invalid_cursor":
        cursor = 777
    result = dict(meta=dict(symbol="XAUUSD", interval=interval, next_cursor=cursor), data=rows)
    return 200, {}, json.dumps(result).encode()


try:
    worker._run(transport=None if scenario == "dns" else transport)
    if scenario == "late_exit":
        time.sleep(60)
except BaseException:
    sys.exit(70)
