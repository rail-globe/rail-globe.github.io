"""Serve the map locally: python3 scripts/serve.py  ->  http://localhost:8765

The page loads its data with fetch(), so it needs HTTP rather than file://.
Keep-alive and a deeper accept queue avoid the dropped connections that
`python -m http.server` shows when a browser opens many requests at once.
The tile archives (data/tiles/*.pmtiles) are read a slice at a time, so the
server answers Range requests as GitHub Pages does; Python's own handler sends
the whole file instead.
"""
import os
import re
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

    def do_GET(self):
        """One byte range of a file: "bytes=a-b", "bytes=a-" or the last n bytes, "bytes=-n"."""
        asked = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        path = self.translate_path(self.path)
        if not asked or not (asked[1] or asked[2]) or not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        if asked[1]:
            first, last = int(asked[1]), min(int(asked[2] or size - 1), size - 1)
        else:
            first, last = max(size - int(asked[2]), 0), size - 1
        if first > last:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        self.send_header("Content-Length", str(last - first + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(first)
            self.wfile.write(f.read(last - first + 1))


class Server(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True


print(f"http://localhost:{PORT}")
Server(("127.0.0.1", PORT), Handler).serve_forever()
