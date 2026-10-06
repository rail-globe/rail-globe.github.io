"""Serve the map locally: python3 scripts/serve.py  ->  http://localhost:8765

The page loads its data with fetch(), so it needs HTTP rather than file://.
Keep-alive and a deeper accept queue avoid the dropped connections that
`python -m http.server` shows when a browser opens many requests at once.
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
os.chdir(Path(__file__).resolve().parents[1])


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class Server(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True


print(f"http://localhost:{PORT}")
Server(("127.0.0.1", PORT), Handler).serve_forever()
