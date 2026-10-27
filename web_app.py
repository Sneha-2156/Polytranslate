"""
web_app.py - PolyTranslate in your browser (standard library only).

    python web_app.py              # opens http://127.0.0.1:8000
    python web_app.py --port 9000 --no-browser

The page speaks translations and listens to your voice using the browser's own speech
engine, so no extra Python packages are needed.
"""
from __future__ import annotations

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import InputError, TranslationError, Translator
from languages import LANGUAGES, SPEECH_TAGS, LanguageError

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "static" / "index.html"
MAX_BODY = 20_000
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def make_handler(translator: Translator):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PolyTranslate/1.0"

        def log_message(self, *args):                       # keep the terminal clean
            pass

        # ------------------------------------------------------------ helpers
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload):
            self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            """Reject requests whose Host isn't localhost (blocks DNS-rebinding tricks)."""
            raw = self.headers.get("Host", "")
            host = raw.split("]")[0] + "]" if raw.startswith("[") else raw.rsplit(":", 1)[0]
            return host in LOCAL_HOSTS

        # -------------------------------------------------------------- routes
        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/languages":
                return self._json(200, {"languages": [
                    {"code": c, "name": n, "speech": SPEECH_TAGS.get(c, c)}
                    for c, n in sorted(LANGUAGES.items(), key=lambda kv: kv[1])]})
            if path == "/api/history":
                return self._json(200, {"items": translator.history.items(30)})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            path = self.path.split("?")[0]
            if path not in ("/api/translate", "/api/history/clear"):
                return self._json(404, {"error": "not found"})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, {"error": "JSON only"})        # also blocks cross-site forms
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                return self._json(400, {"error": "invalid JSON"})

            if path == "/api/history/clear":
                translator.history.clear()
                return self._json(200, {"ok": True})
            try:
                result = translator.translate(
                    str(data.get("text", "")), str(data.get("target", "")),
                    str(data.get("source", "auto")))
            except (LanguageError, InputError) as exc:
                return self._json(400, {"error": str(exc)})
            except TranslationError as exc:                     # every translation service failed
                return self._json(502, {"error": str(exc)})
            self._json(200, result.to_dict())

    return Handler


def make_server(translator: Translator, port: int = 8000, host: str = "127.0.0.1"):
    return ThreadingHTTPServer((host, port), make_handler(translator))


def main():
    parser = argparse.ArgumentParser(description="PolyTranslate web app")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args()

    server = make_server(Translator(data_dir=HERE / "data"), args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"PolyTranslate is running at {url}  (press Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
