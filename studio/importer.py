from __future__ import annotations
import ipaddress
from pathlib import Path
import re
import shutil
import socket
import subprocess
import uuid
from urllib.parse import urlparse
from .config import WORK, VIDEO_EXT, AUDIO_EXT, MAX_ASSET_BYTES, secret, flag
from .media import check_cancel, run_process
from . import store

ALLOWED_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "soundcloud.com", "vimeo.com")


def validate_url(url: str) -> str:
    p = urlparse(url.strip())
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError("URL harus HTTP(S) publik tanpa kredensial/port khusus.")
    allowed = [x.strip().lower() for x in secret("IMPORT_ALLOWED_HOSTS", ",".join(ALLOWED_HOSTS)).split(",") if x.strip()]
    if not any(host == x or host.endswith("."+x) for x in allowed):
        raise ValueError("Host tidak ada dalam allowlist impor. Administrator dapat mengatur IMPORT_ALLOWED_HOSTS.")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError("DNS URL tidak dapat resolved.")
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local:
            raise ValueError("Alamat privat/loopback dilarang untuk impor URL.")
    return p.geturl()


def deno_path() -> str | None:
    from .config import DATA
    candidate = DATA / "bin" / "deno"
    return shutil.which("deno") or (str(candidate) if candidate.is_file() else None)


def download_url(url: str, folder: Path, audio_only=False, cancel=None, progress=None, log=None) -> tuple[Path, dict]:
    url = validate_url(url)
    deno = deno_path()
    if not deno:
        raise RuntimeError("Deno belum tersedia. Jalankan scripts/install_deno.py atau tombol Siapkan Deno di tab Impor.")
    check_cancel(cancel)
    folder.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("yt-dlp")
    base = [exe] if exe else [__import__("sys").executable, "-m", "yt_dlp"]
    common = ["--js-runtimes", "deno:"+deno, "--no-playlist", "--no-progress", "--newline",
              "--socket-timeout", "30", "--retries", "3", "--fragment-retries", "3", "--concurrent-fragments", "2",
              "--max-filesize", str(min(MAX_ASSET_BYTES, 2*1024**3)), "--no-mtime", "--restrict-filenames",
              "--no-exec", "--no-config", "--ignore-config", "--cachedir", str(folder / "cache"),
              "--remote-components", "ejs:npm" if flag("IMPORT_REMOTE_COMPONENTS", True) else "ejs:github"]
    # Probe first. No user-supplied options, cookies, output templates, or shell commands.
    raw = run_process([*base, *common, "--dump-single-json", "--skip-download", url], timeout=120, cancel=cancel)
    import json
    info = json.loads(raw[raw.find("{"):])
    if info.get("duration", 0) > 10800:
        raise ValueError("Durasi maksimum impor ialah 3 jam.")
    if info.get("is_live"):
        raise ValueError("Gunakan tab Live, bukan pengunduh, untuk siaran langsung.")
    prefix = folder / "media"
    fmt = "bestaudio/best" if audio_only else "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    args = [*base, *common, "--format", fmt, "-o", str(prefix)+".%(ext)s", "--print", "after_move:filepath"]
    if audio_only:
        args += ["--extract-audio", "--audio-format", "m4a", "--audio-quality", "0"]
    else:
        args += ["--merge-output-format", "mp4", "--remux-video", "mp4"]
    output = run_process([*args, "--", url], timeout=7200, cancel=cancel, log=log)
    lines = [x.strip() for x in output.splitlines() if x.strip()]
    candidates = [Path(x) for x in lines[-12:] if Path(x).is_file() and Path(x).suffix.lower() in VIDEO_EXT | AUDIO_EXT]
    candidates += [p for p in folder.glob("media.*") if p.suffix.lower() in VIDEO_EXT | AUDIO_EXT]
    if not candidates:
        raise RuntimeError("yt-dlp selesai tanpa berkas media yang dapat diimpor.")
    chosen = max(candidates, key=lambda p: p.stat().st_mtime)
    return chosen, {"source_url": url, "title": info.get("title", ""), "uploader": info.get("uploader", ""),
                    "extractor": info.get("extractor_key", ""), "duration": info.get("duration")}