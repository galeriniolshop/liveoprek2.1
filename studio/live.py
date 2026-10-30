"""Six independent supervisors, each with raw-video + TWO independent PCM FIFOs.
The music feeder never restarts when a short video ends. No shell interpolation.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import threading
import time
import uuid
from .config import RUN, LOGS, secret, flag
from .security import encrypt, decrypt, redact
from . import store
from . import media


ACTIVE = {"starting", "running", "reconnecting", "stopping"}


def pid_alive(pid: int, marker: str | None = None) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        return "studio.live_worker" in cmd and (marker is None or marker in cmd)
    except (ProcessLookupError, PermissionError, FileNotFoundError):
        return False
    except OSError:
        return False


def state(slot: int) -> dict:
    row = store.one("SELECT * FROM lives WHERE slot=?", (slot,))
    if not row:
        return {"slot": slot, "name": f"Slot {slot}", "status": "stopped", "pid": 0, "run_token": "", "heartbeat": 0, "error": "", "stop_requested": 0}
    if row["status"] in ACTIVE and row["pid"] and not pid_alive(row["pid"], row["run_token"]):
        if time.time()-row["heartbeat"] > 20:
            update(slot, status="error", error="Supervisor terputus (reboot/OOM). Start ulang secara manual; siaran tidak otomatis dipublikasikan ulang.", pid=0)
            row = store.one("SELECT * FROM lives WHERE slot=?", (slot,))
    return row


def update(slot, **fields):
    allowed = {"name", "vault", "status", "pid", "run_token", "heartbeat", "stop_requested", "error", "broadcast_id", "updated"}
    if not set(fields) <= allowed:
        raise ValueError("Field live tidak valid")
    fields["updated"] = time.time()
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO lives(slot,name,vault,updated) VALUES(?,?,?,?)", (slot, f"Slot {slot}", encrypt("{}"), time.time()))
        c.execute("UPDATE lives SET "+",".join(k+"=?" for k in fields)+" WHERE slot=?", (*fields.values(), slot))


def config(slot) -> dict:
    row = store.one("SELECT vault FROM lives WHERE slot=?", (slot,))
    return json.loads(decrypt(row["vault"])) if row else {}


def save_config(slot, cfg, name):
    if state(slot)["status"] in ACTIVE:
        raise ValueError("Hentikan slot sebelum mengganti konfigurasi.")
    videos = cfg.get("videos", [])
    audio = cfg.get("audio", [])
    opening = cfg.get("opening")
    if not videos:
        raise ValueError("Pilih minimal satu video playlist.")
    for aid in videos+audio+([opening] if opening else []):
        a = store.asset(aid)
        if a["kind"] != ("audio" if aid in audio else "video"):
            raise ValueError("Jenis aset playlist tidak sesuai.")
    if cfg.get("account_id") and not store.one("SELECT id FROM channels WHERE id=?", (cfg["account_id"],)):
        raise ValueError("Channel OAuth tidak ditemukan.")
    targets = manual_targets(cfg.get("manual_rtmp", ""))
    if not cfg.get("account_id") and not targets:
        raise ValueError("Pilih channel YouTube atau isi minimal satu RTMP/RTMPS.")
    if len(targets)+(1 if cfg.get("account_id") else 0) > 4:
        raise ValueError("Maksimum 4 tujuan simulcast per slot.")
    cfg["manual_rtmp"] = "\n".join(targets)
    store.lock_assets(list(dict.fromkeys(videos+audio+([opening] if opening else []))), f"live:{slot}", replace=True)
    update(slot, vault=encrypt(json.dumps(cfg)), name=name[:60], error="", stop_requested=0)


def manual_targets(text: str) -> list[str]:
    from urllib.parse import urlparse, urlunparse
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        p = urlparse(line)
        if p.scheme not in ("rtmp", "rtmps") or not p.hostname or p.username or p.password or (p.port is not None and not 1 <= p.port <= 65535) or len(p.path) < 2:
            raise ValueError("Setiap baris harus URL RTMP(S) lengkap server/stream-key, tanpa username/password.")
        if any(ch in line for ch in ("\x00", "\n", "|", "[", "]", "\\", "'", '"', " ")):
            raise ValueError("URL RTMP mengandung karakter yang tidak aman untuk tee muxer.")
        result.append(line)
    return list(dict.fromkeys(result))


def start(slot: int) -> int:
    max_slots = max(1, min(6, int(secret("MAX_LIVE_SLOTS", "6"))))
    if slot > max_slots:
        raise ValueError(f"Deployment membatasi {max_slots} slot aktif.")
    with store.connect(True) as c:
        row = c.execute("SELECT * FROM lives WHERE slot=?", (slot,)).fetchone()
        if row and row["status"] in ACTIVE and pid_alive(row["pid"], row["run_token"]):
            raise ValueError("Slot sudah berjalan.")
        running = c.execute("SELECT COUNT(*) FROM lives WHERE status IN ('starting','running','reconnecting','stopping')").fetchone()[0]
        if running >= max_slots:
            raise ValueError("Batas slot aktif tercapai.")
        cfg = json.loads(decrypt(row["vault"])) if row else {}
        if not cfg.get("videos"):
            raise ValueError("Simpan konfigurasi slot terlebih dahulu.")
        run_token = uuid.uuid4().hex
        now = time.time()
        c.execute("UPDATE lives SET status='starting',run_token=?,heartbeat=?,stop_requested=0,error='',pid=0,broadcast_id='' WHERE slot=?",
                  (run_token, now, slot))
    logpath = LOGS / f"live-{slot}.log"
    with logpath.open("a") as log:
        p = subprocess.Popen([__import__("sys").executable, "-m", "studio.live_worker", str(slot), run_token],
                             cwd=Path(__file__).resolve().parents[1], stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    update(slot, pid=p.pid)
    return p.pid


def stop(slot: int, force=False):
    row = state(slot)
    update(slot, stop_requested=1, status="stopping")
    if row.get("pid") and pid_alive(row["pid"], row.get("run_token")):
        if force:
            os.killpg(row["pid"], signal.SIGKILL)
        else:
            os.killpg(row["pid"], signal.SIGTERM)
    else:
        update(slot, status="stopped", pid=0)


def log_tail(slot, limit=18000):
    p = LOGS / f"live-{slot}.log"
    return redact(p.read_text(errors="replace")[-limit:]) if p.exists() else "Belum ada log."


def tee_destination(urls: list[str]) -> str:
    # Reject rather than silently corrupt keys. Escaping is still applied for ':' and ',' in query strings.
    manual_targets("\n".join(urls))
    if not 1 <= len(urls) <= 4:
        raise ValueError("Tee memerlukan 1–4 tujuan.")
    slaves = []
    for url in urls:
        escaped = url.replace(":", "\\:").replace(",", "\\,")
        slaves.append("[f=flv:onfail=ignore]"+escaped)
    return "|".join(slaves)


def ffmpeg_command(folder: Path, width, height, fps, bitrate, targets, music_volume=.35, original_volume=.8):
    return ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
            "-thread_queue_size", "512", "-f", "rawvideo", "-pixel_format", "yuv420p",
            "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", str(folder/"video.fifo"),
            "-thread_queue_size", "128", "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", str(folder/"music.fifo"),
            "-thread_queue_size", "128", "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", str(folder/"original.fifo"),
            "-filter_complex_threads", "1", "-filter_complex",
            f"[1:a]volume={music_volume}[m];[2:a]volume={original_volume}[o];"
            "[m][o]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.90,aresample=async=1:first_pts=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-threads", "2", "-pix_fmt", "yuv420p", "-g", str(fps*2), "-keyint_min", str(fps*2), "-sc_threshold", "0",
            "-b:v", f"{bitrate}k", "-maxrate", f"{bitrate}k", "-bufsize", f"{bitrate*2}k",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-flvflags", "no_duration_filesize",
            "-f", "tee", tee_destination(targets)]