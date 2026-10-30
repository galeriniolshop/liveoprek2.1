"""Standalone local/VPS resumable uploader, port 8502. Not available as a public port on Cloud.
Browser calls relative URLs on THIS server. No CORS bypass, no arbitrary filesystem paths.
"""
from __future__ import annotations
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from studio.config import DATA, INCOMING, MAX_ASSET_BYTES, asset_kind, ensure_dirs, secret
from studio import store
from studio.media import probe

LOCKS: dict[str, threading.Lock] = {}
GUARD = threading.Lock()
FAILURES: dict[str, list[float]] = {}
MAX_CHUNK = 8 * 1024**2


def upload_token():
    ensure_dirs()
    value = secret("UPLOAD_TOKEN")
    if value:
        if len(value) < 24:
            raise ValueError("UPLOAD_TOKEN minimal 24 karakter.")
        return value
    p = DATA / "upload.token"
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return p.read_text().strip()


def session_path(sid):
    if len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
        raise ValueError("ID sesi tidak valid")
    return INCOMING / sid


def read_meta(sid):
    return json.loads(Path(str(session_path(sid))+".json").read_text())


def write_meta(sid, data):
    p = Path(str(session_path(sid))+".json")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, p)


class Handler(BaseHTTPRequestHandler):
    server_version = "liveoprek-upload/1.0"
    def log_message(self, fmt, *args):
        # Do not log URLs, authorization headers, filenames or tokens.
        pass

    def send(self, status, body, content_type="application/json"):
        raw = json.dumps(body, ensure_ascii=False).encode() if content_type == "application/json" else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type+("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        ip = self.client_address[0]
        with GUARD:
            FAILURES[ip] = [t for t in FAILURES.get(ip, []) if time.time()-t < 60]
            if len(FAILURES[ip]) >= 12:
                self.send(429, {"error": "Terlalu banyak percobaan token. Tunggu satu menit."})
                return False
        if not hmac.compare_digest(supplied, "Bearer "+upload_token()):
            with GUARD:
                FAILURES[ip] = FAILURES.get(ip, [])+[time.time()]
            self.send(401, {"error": "Token uploader tidak cocok."})
            return False
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self.send(403, {"error": "Origin tidak diizinkan."})
            return False
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send(200, (Path(__file__).parent / "studio" / "upload.html").read_text(), "text/html")
            return
        if path == "/health":
            self.send(200, {"ok": True, "service": "liveoprek2 resumable upload", "chunk_limit": MAX_CHUNK})
            return
        if path == "/api/download":
            pass  # Short-lived HMAC capability is checked in the branch below.
        elif not self.authorized():
            return
        if path == "/api/download":
            try:
                from studio.downloads import signature
                q = parse_qs(urlparse(self.path).query)
                aid, expires = q["asset"][0], int(q["expires"][0])
                supplied = q.get("signature", [""])[0]
                if expires < time.time() or expires > time.time()+600 or not hmac.compare_digest(signature(aid, expires), supplied):
                    raise ValueError("Tautan kedaluwarsa/tidak valid.")
                a = store.asset(aid)
                p = Path(store.asset_path(a))
                if not p.is_relative_to(Path(__import__("studio.config", fromlist=["LIBRARY"]).LIBRARY)) or not p.is_file():
                    raise ValueError("Berkas tidak tersedia.")
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(p.stat().st_size))
                from urllib.parse import quote
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''"+quote(a["name"]))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with p.open("rb") as f:
                    while block := f.read(1024*1024):
                        self.wfile.write(block)
            except (KeyError, ValueError, FileNotFoundError):
                self.send(403, {"error": "Tautan unduh tidak valid atau kedaluwarsa."})
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if path.startswith("/api/session/"):
            try:
                meta = read_meta(path.rsplit("/", 1)[-1])
                self.send(200, {"offset": meta["offset"], "size": meta["size"], "name": meta["name"], "complete": meta["complete"], "asset": meta.get("asset")})
            except (ValueError, FileNotFoundError):
                self.send(404, {"error": "Sesi tidak ditemukan."})
        else:
            self.send(404, {"error": "Tidak ditemukan."})

    def do_POST(self):
        if not self.authorized():
            return
        if urlparse(self.path).path != "/api/session":
            self.send(404, {"error": "Tidak ditemukan."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 16384:
                raise ValueError("Metadata terlalu besar/kosong.")
            data = json.loads(self.rfile.read(length))
            name = Path(str(data["name"]).replace("\\", "/")).name
            size = int(data["size"])
            if size <= 0 or size > MAX_ASSET_BYTES:
                raise ValueError("Ukuran berkas tidak valid/melebihi batas.")
            kind = asset_kind(Path(name).suffix)
            import shutil
            if shutil.disk_usage(DATA).free < size+256*1024**2:
                raise ValueError("Disk tidak cukup untuk menyelesaikan impor.")
            sid = secrets.token_hex(16)
            p = session_path(sid)
            p.touch(exist_ok=False)
            meta = {"name": name, "size": size, "offset": 0, "complete": False, "kind": kind, "created": time.time()}
            write_meta(sid, meta)
            self.send(201, {"id": sid, "offset": 0})
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self.send(400, {"error": str(e)})

    def do_PATCH(self):
        if not self.authorized():
            return
        path = urlparse(self.path).path
        if not path.startswith("/api/session/"):
            self.send(404, {"error": "Tidak ditemukan."})
            return
        sid = path.rsplit("/", 1)[-1]
        try:
            session_path(sid)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_CHUNK:
                self.send(413, {"error": "Chunk harus 0 byte sampai 8 MiB."})
                return
            with GUARD:
                lock = LOCKS.setdefault(sid, threading.Lock())
            with lock:
                meta = read_meta(sid)
                offset = int(self.headers.get("Upload-Offset", "-1"))
                if meta["complete"]:
                    self.send(200, {"offset": meta["offset"], "complete": True, "asset": meta.get("asset")})
                    return
                if offset != meta["offset"]:
                    self.send(409, {"error": "Offset tidak cocok.", "offset": meta["offset"]})
                    return
                if offset+length > meta["size"]:
                    raise ValueError("Chunk melampaui ukuran yang dideklarasikan.")
                remaining = length
                with session_path(sid).open("r+b") as f:
                    f.seek(offset)
                    while remaining:
                        block = self.rfile.read(min(65536, remaining))
                        if not block:
                            raise ValueError("Koneksi putus di tengah chunk; ulangi dari offset tersimpan.")
                        f.write(block)
                        remaining -= len(block)
                    f.flush()
                    os.fsync(f.fileno())
                meta["offset"] += length
                if meta["offset"] == meta["size"]:
                    asset = store.import_file(session_path(sid), meta["name"], "resumable-8502", move=True)
                    meta["complete"], meta["asset"] = True, {"id": asset["id"], "name": asset["name"]}
                write_meta(sid, meta)
                self.send(200, {"offset": meta["offset"], "complete": meta["complete"], "asset": meta.get("asset")})
        except FileNotFoundError:
            self.send(404, {"error": "Sesi tidak ditemukan."})
        except (ValueError, RuntimeError) as e:
            self.send(400, {"error": str(e)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8502)
    args = parser.parse_args()
    ensure_dirs()
    store.init()
    upload_token()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"Resumable uploader listening on {args.host}:{args.port}; token required.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()