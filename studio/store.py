"""SQLite WAL repository. All cross-process state lives here, not session_state."""
from __future__ import annotations
import contextlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from .config import DB, DATA, LIBRARY, MAX_ASSET_BYTES, ensure_dirs, asset_kind
from .security import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,
 path TEXT NOT NULL UNIQUE,bytes INTEGER NOT NULL,sha256 TEXT DEFAULT '',created REAL NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}',origin TEXT NOT NULL DEFAULT 'local');
CREATE TABLE IF NOT EXISTS refs(asset_id TEXT NOT NULL,owner TEXT NOT NULL,
 PRIMARY KEY(asset_id,owner),FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,label TEXT NOT NULL,
 payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',progress REAL NOT NULL DEFAULT 0,
 stage TEXT NOT NULL DEFAULT 'Menunggu',error TEXT NOT NULL DEFAULT '',result TEXT NOT NULL DEFAULT '{}',
 created REAL NOT NULL,updated REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY,v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY,channel_id TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL,thumbnail TEXT NOT NULL DEFAULT '',vault TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth(state TEXT PRIMARY KEY,verifier TEXT NOT NULL,browser_hash TEXT NOT NULL,
 created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lives(slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 6),
 name TEXT NOT NULL,vault TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'stopped',pid INTEGER DEFAULT 0,
 run_token TEXT NOT NULL DEFAULT '',heartbeat REAL NOT NULL DEFAULT 0,stop_requested INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '',broadcast_id TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,asset_id TEXT NOT NULL,channel_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,session_uri TEXT NOT NULL DEFAULT '',offset INTEGER NOT NULL DEFAULT 0,
 video_id TEXT NOT NULL DEFAULT '',metadata TEXT NOT NULL,updated REAL NOT NULL);
"""


@contextlib.contextmanager
def connect(immediate: bool = False):
    ensure_dirs()
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    try:
        if immediate:
            con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


def rows(query: str, args=()) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(query, args).fetchall()]


def one(query: str, args=()) -> dict | None:
    result = rows(query, args)
    return result[0] if result else None


def kv_get(key: str, default=None):
    row = one("SELECT v FROM kv WHERE k=?", (key,))
    return json.loads(row["v"]) if row else default


def kv_set(key: str, value) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (key, json.dumps(value)))


def safe_path(path: str | Path) -> Path:
    p = Path(path).resolve()
    if not p.is_relative_to(DATA):
        raise ValueError("Path berada di luar penyimpanan aplikasi.")
    return p


def register(path: str | Path, name: str, origin: str = "local", sha256: str = "", metadata: dict | None = None) -> dict:
    p = safe_path(path)
    if not p.is_file() or not p.stat().st_size:
        raise ValueError("Berkas kosong atau tidak ditemukan.")
    kind = asset_kind(p.suffix)
    aid = uuid.uuid4().hex
    with connect(True) as c:
        c.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, Path(name).name[:220], kind, str(p.relative_to(DATA)), p.stat().st_size,
                   sha256, time.time(), json.dumps(metadata or {}), origin))
    return asset(aid)


def import_file(path: str | Path, name: str, origin: str = "local", metadata: dict | None = None, move: bool = True) -> dict:
    from .media import probe, sha256
    p = safe_path(path)
    info = probe(p)
    suffix = p.suffix.lower() or Path(name).suffix.lower()
    kind = asset_kind(suffix)
    if p.stat().st_size > MAX_ASSET_BYTES:
        raise ValueError("Berkas melebihi MAX_ASSET_BYTES.")
    stream_types = {s.get("codec_type") for s in info.get("streams", [])}
    if kind == "image":
        from PIL import Image
        with Image.open(p) as im:
            im.verify()
    elif kind not in stream_types:
        raise ValueError(f"Isi berkas tidak cocok dengan ekstensi {suffix}; diharapkan stream {kind}.")
    digest = sha256(p)
    existing = one("SELECT * FROM assets WHERE sha256=? AND bytes=?", (digest, p.stat().st_size))
    if existing and Path(asset_path(existing)).is_file():
        if move and p != Path(asset_path(existing)):
            p.unlink(missing_ok=True)
        return existing
    target = LIBRARY / f"{uuid.uuid4().hex}{suffix}"
    import shutil
    if shutil.disk_usage(LIBRARY).free < p.stat().st_size + 64*1024**2:
        raise ValueError("Disk tidak cukup untuk menyalin aset secara atomik.")
    shutil.copy2(p, target)
    try:
        result = register(target, name, origin, digest, metadata)
        if move:
            p.unlink(missing_ok=True)
        return result
    except Exception:
        target.unlink(missing_ok=True)
        raise


def asset(aid: str) -> dict:
    a = one("SELECT * FROM assets WHERE id=?", (aid,))
    if not a:
        raise ValueError("Aset tidak ditemukan.")
    a["metadata"] = json.loads(a["metadata"])
    return a


def asset_path(a: dict | str) -> str:
    if isinstance(a, str):
        a = asset(a)
    return str(safe_path(DATA / a["path"]))


def assets(kind: str = "all", search: str = "") -> list[dict]:
    q, args = "SELECT * FROM assets WHERE 1=1", []
    if kind != "all":
        q += " AND kind=?"
        args.append(kind)
    if search:
        q += " AND lower(name) LIKE ?"
        args.append(f"%{search.lower()}%")
    result = rows(q + " ORDER BY created DESC", args)
    for a in result:
        a["metadata"] = json.loads(a["metadata"])
    return result


def lock_assets(ids: list[str], owner: str, replace: bool = False) -> None:
    with connect(True) as c:
        if replace:
            c.execute("DELETE FROM refs WHERE owner=?", (owner,))
        for aid in dict.fromkeys(ids):
            if not c.execute("SELECT 1 FROM assets WHERE id=?", (aid,)).fetchone():
                raise ValueError("Aset sudah dihapus; muat ulang pilihan.")
            c.execute("INSERT OR IGNORE INTO refs VALUES(?,?)", (aid, owner))


def unlock(owner: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM refs WHERE owner=?", (owner,))


def references(aid: str) -> list[str]:
    return [r["owner"] for r in rows("SELECT owner FROM refs WHERE asset_id=?", (aid,))]


def delete_asset(aid: str, confirm: bool = False) -> None:
    if not confirm:
        raise ValueError("Konfirmasi penghapusan diperlukan.")
    with connect(True) as c:
        row = c.execute("SELECT path FROM assets WHERE id=?", (aid,)).fetchone()
        if not row:
            return
        if c.execute("SELECT owner FROM refs WHERE asset_id=? LIMIT 1", (aid,)).fetchone():
            raise ValueError("Aset dipakai job aktif atau slot live. Batalkan job / keluarkan dari playlist dahulu.")
        p = safe_path(DATA / row["path"])
        # The transaction serializes deletion against new job/live references.
        p.unlink(missing_ok=True)
        c.execute("DELETE FROM assets WHERE id=?", (aid,))


def enqueue(kind: str, label: str, payload: dict, inputs: list[str] | None = None) -> str:
    jid = uuid.uuid4().hex
    now = time.time()
    with connect(True) as c:
        c.execute("INSERT INTO jobs(id,kind,label,payload,created,updated) VALUES(?,?,?,?,?,?)",
                  (jid, kind, label[:180], json.dumps(payload), now, now))
        for aid in dict.fromkeys(inputs or []):
            if not c.execute("SELECT id FROM assets WHERE id=?", (aid,)).fetchone():
                raise ValueError("Aset masukan tidak tersedia.")
            c.execute("INSERT OR IGNORE INTO refs VALUES(?,?)", (aid, "job:" + jid))
    return jid


def job(jid: str) -> dict:
    j = one("SELECT * FROM jobs WHERE id=?", (jid,))
    if not j:
        raise ValueError("Job tidak ditemukan.")
    for k in ("payload", "result"):
        j[k] = json.loads(j[k])
    return j


def update_job(jid: str, **fields) -> None:
    allowed = {"status", "progress", "stage", "error", "result", "attempts"}
    if not set(fields) <= allowed:
        raise ValueError("Field job tidak sah")
    if "result" in fields:
        fields["result"] = json.dumps(fields["result"])
    if "error" in fields:
        fields["error"] = redact(str(fields["error"]))[-4000:]
    fields["updated"] = time.time()
    with connect() as c:
        c.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                  (*fields.values(), jid))


def claim_job() -> dict | None:
    with connect(True) as c:
        r = c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if not r:
            return None
        c.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated=?,stage='Mulai' WHERE id=?", (time.time(), r["id"]))
        return job(r["id"])


def log(jid: str, message: str) -> None:
    from .config import LOGS
    with (LOGS / (jid + ".log")).open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {redact(str(message))[-3000:]}\n")


def log_tail(jid: str, limit: int = 16000) -> str:
    from .config import LOGS
    p = LOGS / (jid + ".log")
    return p.read_text(errors="replace")[-limit:] if p.exists() else "Belum ada log."