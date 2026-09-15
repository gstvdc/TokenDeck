"""Local HTTP bridge serving Claude and Codex usage to the Wi-Fi display."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from daemon.codex_usage_daemon_windows import read_codex_payload
from daemon.claude_usage_daemon_windows import AuthError, poll_api, read_token

HOST = "0.0.0.0"
PORT = 8787
cache_lock = threading.Lock()
cache = {
    "/api/codex": {"p": "codex", "ok": False},
    "/api/claude": {"p": "claude", "ok": False},
}


def store(path: str, payload: dict | None, provider: str) -> None:
    value = dict(payload) if payload else {"ok": False}
    value["p"] = provider
    with cache_lock:
        cache[path] = value


def refresh_loop() -> None:
    next_claude = 0.0
    while True:
        try:
            store("/api/codex", read_codex_payload(), "codex")
            now = time.monotonic()
            if now >= next_claude:
                token = read_token()
                try:
                    payload = asyncio.run(poll_api(token)) if token else None
                except AuthError:
                    payload = None
                except Exception as exc:
                    print(f"[{time.strftime('%H:%M:%S')}] Claude poll error: {exc}")
                    payload = None
                store("/api/claude", payload, "claude")
                next_claude = now + 60
        except Exception as exc:
            print(f"[{time.strftime('%H:%M:%S')}] Refresh loop error: {exc}")
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = b'{"ok":true}'
        elif self.path in cache:
            with cache_lock:
                body = json.dumps(cache[self.path], separators=(",", ":")).encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")


def main() -> None:
    threading.Thread(target=refresh_loop, daemon=True).start()
    print(f"TokenMeter bridge: http://{HOST}:{PORT}")
    print("Pressione Ctrl+C para parar.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTokenMeter bridge finalizado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
