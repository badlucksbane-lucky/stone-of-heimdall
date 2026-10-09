#!/usr/bin/env python3
"""preview-ui.py [--port 8100] [--bind 0.0.0.0] [--writes]

Serve the working-tree ui.html (re-read on every request, so an edit shows on reload) against the REAL router's data, to look at a UI change in a browser or on a phone before it is
committed or deployed. GET /api/* and /status.json are passed through to the Orbic (HTTPS :3129, certificate pinned from ~/.heimdallstone/orbic-tls.pem, token from
~/.heimdallstone/ui.token, never printed or sent to the browser). POSTs are NOT sent: they answer "preview" and change nothing, unless --writes is given.

The page has no login here, so access is gated by a random key printed at start: open the URL once and a cookie remembers it. Stop the script when done.
"""
import argparse, http.server, os, secrets, socketserver, ssl, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~/.heimdallstone")
BASE = "https://orbic:3129"
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8100)
ap.add_argument("--bind", default="0.0.0.0")
ap.add_argument("--writes", action="store_true", help="forward POSTs to the router (default: block them)")
a = ap.parse_args()

TOKEN = open(os.path.join(HOME, "ui.token")).read().strip()
CTX = ssl.create_default_context(cafile=os.path.join(HOME, "orbic-tls.pem"))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=CTX))
KEY = secrets.token_urlsafe(9)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):  # the key travels in a URL once; keep it out of any log
        pass

    def send(self, code, body, ctype="application/json", extra=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        if f"pk={KEY}" in (self.headers.get("Cookie") or ""):
            return True
        if self.path.startswith("/?k=") and self.path[4:] == KEY:
            self.send(302, "", "text/plain", [("Location", "/"), ("Set-Cookie", f"pk={KEY}; Path=/; HttpOnly; SameSite=Strict")])
            return None
        self.send(403, "locked: open the URL that preview-ui.py printed", "text/plain")
        return None

    def forward(self, method, body=None):
        req = urllib.request.Request(BASE + self.path, data=body, method=method, headers={"X-UI-Token": TOKEN, "Content-Type": "application/json"})
        try:
            with OPENER.open(req, timeout=15) as r:
                self.send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as e:
            self.send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
        except Exception as e:  # router unreachable
            self.send(502, '{"error":"preview: router unreachable"}')

    def do_GET(self):
        if not self.authed():
            return
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self.send(200, open(os.path.join(HERE, "ui.html"), "rb").read(), "text/html; charset=utf-8")
        if p == "/favicon.svg":
            return self.send(200, open(os.path.join(HERE, "assets", "mark.svg"), "rb").read(), "image/svg+xml")
        if p == "/api/session":
            return self.send(200, '{"csrf":"preview","user":"preview"}')
        if p.startswith("/api/") and ("stream" in p or p.startswith("/api/tap")):
            return self.send(404, '{"error":"preview: streaming endpoints are not passed through"}')
        if p.startswith("/api/") or p == "/status.json":
            return self.forward("GET")
        self.send(404, "not found", "text/plain")

    def do_POST(self):
        if not self.authed():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if a.writes and self.path.startswith("/api/"):
            return self.forward("POST", body)
        self.send(200, '{"status":"preview: nothing was sent to the router"}')


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    import socket
    ip = a.bind
    if ip == "0.0.0.0":  # the address a phone on this LAN can reach (not the 127.0.1.1 that the hostname resolves to)
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.connect(("192.168.1.254", 9))
            ip = u.getsockname()[0]
        except OSError:
            ip = "127.0.0.1"
        finally:
            u.close()
    print(f"preview of ./ui.html with live data ({'WRITES ON' if a.writes else 'read-only'}): http://{ip}:{a.port}/?k={KEY}", flush=True)
    S((a.bind, a.port), H).serve_forever()
