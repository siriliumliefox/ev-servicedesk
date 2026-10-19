"""Приёмник алертов локального стенда (глава 26, ADR 0030 п. 23): вместо Telegram и dead-man.

POST /<канал> — webhook Alertmanager; строка JSON с временем приёма — в /data/alerts.jsonl.
GET /alerts — весь журнал (для scripts/infra_stack.sh drill-alerts). Только стандартная библиотека.
"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = Path("/data/alerts.jsonl")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — имя метода задаёт http.server
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = {"raw": body.decode(errors="replace")}
        entry = {"received_at": time.time(), "channel": self.path.strip("/"), "payload": payload}
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        data = LOG.read_bytes() if LOG.exists() else b""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
