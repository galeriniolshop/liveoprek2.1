"""Persistent, single-instance render/import/upload queue; independent of browser sessions."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import time
from .config import ROOT, RUN, WORK, LOGS, ANALYSIS, secret, flag
from . import store, media, render, ai, importer, tts, youtube

STOP = False


def request_stop(*_):
    global STOP
    STOP = True


def ensure_worker() -> dict:
    pids = store.kv_get("worker", {})
    pid = int(pids.get("pid", 0))
    if pid:
        try:
            os.kill(pid, 0)
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            if "studio.worker" in cmd:
                return {"running": True, "pid": pid}
        except (OSError, FileNotFoundError):
            pass
    if not flag("AUTO_START_WORKER", True):
        return {"running": False, "pid": 0}
    with (LOGS/"worker.log").open("a") as log:
        p = subprocess.Popen([sys.executable, "-m", "studio.worker"], cwd=ROOT, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    store.kv_set("worker", {"pid": p.pid, "started": time.time()})
    return {"running": True, "pid": p.pid}


def recover_interrupted():
    # Executed only AFTER the singleton lock is held. Never blindly retry an upload after OOM.
    for j in store.rows("SELECT id FROM jobs WHERE status='running'"):
        store.update_job(j["id"], status="error", error="Worker pernah berhenti/OOM. Retry manual; sesi upload YouTube tersimpan.", stage="Terinterupsi")
        store.unlock("job:"+j["id"])


def cancel(jid):
    return bool(store.one("SELECT id FROM jobs WHERE id=? AND (status='cancelled' OR (status='running' AND stage='Membatalkan…'))", (jid,)))


def extract_frames(source, folder, seconds):
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    for i, fraction in enumerate((.15, .45, .75)):
        p = folder / f"frame-{i}.jpg"
        media.ffmpeg(["-ss", f"{seconds*fraction:.3f}", "-i", source, "-frames:v", "1", "-vf", "scale=384:-2", str(p)], timeout=60)
        result.append(str(p))
    return result


def execute(j: dict):
    jid, kind, p = j["id"], j["kind"], j["payload"]
    folder = WORK / jid
    folder.mkdir(parents=True, exist_ok=True)
    cb = lambda: STOP or cancel(jid)
    def progress(value):
        store.update_job(jid, progress=max(0, min(.99, value)))
    def stage(text, value=None):
        media.check_cancel(cb)
        store.update_job(jid, stage=text, **({"progress": value} if value is not None else {}))
        store.log(jid, text)
    def output_file(a, metadata=None):
        return store.import_file(a, a.name, kind, metadata=metadata or {})
    result = {}
    if kind == "import_url":
        stage("Mengambil metadata dan mengunduh via yt-dlp + Deno", .03)
        path, meta = importer.download_url(p["url"], folder, p.get("audio_only", False), cb,
                                          log=lambda s: store.log(jid, s))
        stage("Validasi ffprobe dan masukkan Library", .9)
        a = store.import_file(path, meta.get("title", "Impor URL")[:150]+path.suffix, "yt-dlp", meta)
        result = {"asset_id": a["id"], "name": a["name"]}
    elif kind in ("clipdrop_motion", "poem"):
        image = store.asset_path(p["image_id"])
        draft = p.get("draft")
        if kind == "poem" and not draft:
            stage("Riset web nyata + penyusunan bait Ollama", .03)
            research = ai.web_research(p["topic"], "poem", p.get("account_id"), cb)
            draft = ai.poem(p["topic"], research, p.get("signature", "ruang miring"), cb)
        music_ids = p.get("music_ids", [])
        music = store.asset_path(random.choice(music_ids)) if music_ids else None
        seconds = max(5, min(60, float(p.get("seconds", 15))))
        width = 720 if p.get("resolution") == "720p" else 1080
        stage("Render zoompan + partikel + musik 9:16", .15)
        target = folder / "shorts.mp4"
        render.motion_video(image, str(target), folder, p.get("effect", "rain"), seconds, music,
                            draft if kind == "poem" else None, width, width*16//9//2*2,
                            cb, lambda v: progress(.15+.75*v))
        stage("Masukkan MP4 ke Library", .94)
        a = output_file(target, {"draft": draft} if draft else {})
        result = {"asset_id": a["id"], "name": a["name"], "metadata": draft or p.get("metadata", {})}
    elif kind == "reaction":
        source = store.asset_path(p["source_id"])
        seconds = min(max(5, float(p.get("seconds", 30))), media.duration(source), 60)
        draft = p.get("draft")
        analysis = ANALYSIS/jid
        if not draft:
            stage("Ambil sampel frame + naskah reaksi Ollama", .03)
            frames = extract_frames(source, analysis, seconds)
            research = ai.web_research(p.get("context", "kejadian lucu"), "reaction", p.get("account_id"), cb) if p.get("research") else None
            draft = ai.reaction(p.get("context", ""), seconds, research, frames, cb)
        stage("Sintesis narator Bahasa Indonesia per kalimat", .13)
        segments = tts.synthesize(draft["lines"], folder, p.get("voice", "id-ID-GadisNeural"),
                                  p.get("rate", "+0%"), p.get("fallback_tts", False), cb)
        stage("Selaraskan subtitle dengan durasi TTS aktual", .26)
        narration, timed = render.build_narration(segments, folder, seconds, cb)
        (analysis).mkdir(parents=True, exist_ok=True)
        (analysis/"reaction.srt").write_text(render.srt_text(timed), encoding="utf-8")
        (analysis/"reaction.json").write_text(json.dumps({"draft": draft, "subtitles": timed}, ensure_ascii=False), encoding="utf-8")
        stage("Mix ducking audio asli + TTS + banner + subtitle", .32)
        target = folder / "reaction.mp4"
        render.reaction_video(source, str(target), folder, draft["banner"], narration, timed, seconds,
                              720 if p.get("resolution") == "720p" else 1080,
                              1280 if p.get("resolution") == "720p" else 1920,
                              p.get("crop", True), cb, lambda v: progress(.32+.58*v))
        a = output_file(target, {"draft": draft})
        result = {"asset_id": a["id"], "name": a["name"], "metadata": draft, "srt": str(analysis/"reaction.srt")}
    elif kind in ("normalize_audio", "normalize_video"):
        source = store.asset_path(p["asset_id"])
        audio = kind == "normalize_audio"
        stage("Ukur loudness EBU R128 (pass 1)", .05)
        target = folder / ("normalized.m4a" if audio else "normalized.mp4")
        if audio:
            media.normalize_audio(source, target, p.get("target", -16), cb, lambda v: progress(.2+.7*v))
        else:
            w, h = (720, 1280) if p.get("vertical") else (1280, 720)
            media.normalize_video(source, target, w, h, p.get("target", -16), cb, lambda v: progress(.2+.7*v))
        stage("Simpan hasil normalisasi", .94)
        a = output_file(target)
        result = {"asset_id": a["id"], "name": a["name"]}
    elif kind == "youtube_upload":
        a = store.asset(p["asset_id"])
        if not p.get("consent"):
            raise ValueError("Persetujuan upload/publikasi tidak ditemukan.")
        stage("Google Resumable Upload · chunk 8 MiB", .01)
        result = youtube.upload_video(p["account_id"], a, p["metadata"], jid, progress, cb)
    else:
        raise ValueError("Jenis job tidak dikenal: "+kind)
    media.check_cancel(cb)
    store.update_job(jid, status="done", progress=1, stage="Selesai", result=result)
    if p.get("auto_upload") and p.get("consent") and result.get("asset_id") and kind != "youtube_upload":
        metadata = dict(result.get("metadata") or p.get("metadata") or {"title": result.get("name", "Video baru"), "description": "#Shorts"})
        metadata.update({"privacy": p.get("privacy", "private"), "synthetic": p.get("synthetic", True),
                         "made_for_kids": p.get("made_for_kids", False)})
        if "hashtags" not in metadata:
            metadata["hashtags"] = ["#Shorts"]
        upload_id = store.enqueue("youtube_upload", "Upload: "+metadata.get("title", "Hasil render"),
                                  {"asset_id": result["asset_id"], "account_id": p["account_id"], "metadata": metadata, "consent": True},
                                  [result["asset_id"]])
        store.update_job(jid, result={**result, "upload_job_id": upload_id})


def main():
    store.init()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with (RUN/"worker.lock").open("w") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Worker sudah berjalan.", flush=True)
            return
        recover_interrupted()
        store.kv_set("worker", {"pid": os.getpid(), "started": time.time()})
        print("Worker aktif; antrean persisten SQLite.", flush=True)
        while not STOP:
            j = store.claim_job()
            if not j:
                time.sleep(1)
                continue
            try:
                execute(j)
            except media.Cancelled as exc:
                store.update_job(j["id"], status="cancelled", stage="Dibatalkan", error=str(exc))
            except Exception as exc:
                store.update_job(j["id"], status="error", stage="Gagal", error=str(exc))
                store.log(j["id"], str(exc))
            finally:
                store.unlock("job:"+j["id"])
                if flag("CLEAN_JOB_TEMP", True):
                    shutil.rmtree(WORK/j["id"], ignore_errors=True)
        print("Worker berhenti atas permintaan.", flush=True)


if __name__ == "__main__":
    main()