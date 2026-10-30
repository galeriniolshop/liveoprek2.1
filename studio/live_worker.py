from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import threading
import time
from .config import RUN, ANALYSIS
from .security import decrypt, redact
from . import store, live, media, ai, youtube


_ACTIVE_WORKER = None


def _terminate(signum, frame):
    if _ACTIVE_WORKER is not None:
        _ACTIVE_WORKER.stop_event.set()


class Supervisor:
    def __init__(self, slot, run_token):
        self.slot, self.run_token = slot, run_token
        self.cfg = live.config(slot)
        self.folder = RUN / f"slot-{slot}-{run_token}"
        self.folder.mkdir(mode=0o700, parents=True)
        self.stop_event = threading.Event()
        self.output_ready = threading.Event()
        self.children: set[subprocess.Popen] = set()
        self.guard = threading.Lock()
        self.main = None
        self.account = self.cfg.get("account_id")
        self.broadcast = ""
        self.info = None
        self.fatal = None
        self.width, self.height = (720, 1280) if self.cfg.get("vertical") else (1280, 720)
        self.fps = int(self.cfg.get("fps", 24))
        self.frame_size = self.width*self.height*3//2
        self.last_video = None
        self.music_deck = []
        self.video_deck = []

    def log(self, text):
        print(time.strftime("%Y-%m-%d %H:%M:%S"), redact(str(text)), flush=True)

    def stopping(self):
        if self.stop_event.is_set():
            return True
        row = store.one("SELECT stop_requested,run_token FROM lives WHERE slot=?", (self.slot,))
        if not row or row["run_token"] != self.run_token or row["stop_requested"]:
            self.stop_event.set()
        return self.stop_event.is_set()

    def spawn(self, args):
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True)
        with self.guard:
            self.children.add(p)
        return p

    def kill(self, p):
        if p is None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(timeout=3)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        with self.guard:
            self.children.discard(p)
        if p.stdout:
            p.stdout.close()
        if p.stderr:
            p.stderr.close()

    def open_fifo(self, name):
        deadline = time.time()+30
        while not self.stopping():
            try:
                fd = os.open(self.folder/name, os.O_WRONLY | os.O_NONBLOCK)
                os.set_blocking(fd, True)
                return fd
            except OSError as exc:
                if exc.errno != 6 and time.time() > deadline:
                    raise
                time.sleep(.1)
        raise RuntimeError("Supervisor dihentikan sebelum FIFO siap.")

    def write_all(self, fd, data):
        view = memoryview(data)
        while view and not self.stopping():
            try:
                n = os.write(fd, view)
                view = view[n:]
            except BlockingIOError:
                time.sleep(.01)
            except BrokenPipeError:
                raise RuntimeError("FFmpeg menutup pipe.")

    def decode(self, path, fifo, args, duration=None):
        fd = self.open_fifo(fifo)
        p = self.spawn(args)
        error = []
        def drain():
            for line in p.stderr:
                error.append(redact(line.decode(errors="replace").rstrip()))
                del error[:-5]
        t = threading.Thread(target=drain, daemon=True)
        t.start()
        try:
            while not self.stopping():
                data = p.stdout.read(65536)
                if not data:
                    break
                self.write_all(fd, data)
            if self.stopping():
                return
            p.wait(timeout=15)
            t.join(timeout=2)
            if p.returncode:
                raise RuntimeError("Decoder gagal: "+" ".join(error[-3:]))
        finally:
            self.kill(p)
            os.close(fd)

    def silence(self, fifo, seconds):
        self.decode(None, fifo, ["ffmpeg", "-v", "error", "-nostdin", "-re", "-f", "lavfi", "-i",
                                "anullsrc=r=48000:cl=stereo", "-t", f"{max(.1,seconds):.3f}", "-f", "s16le", "pipe:1"])

    def music_loop(self):
        paths = [store.asset_path(a) for a in self.cfg.get("audio", [])]
        while not self.stopping():
            if not self.output_ready.wait(.2):
                continue
            try:
                if not paths:
                    self.silence("music.fifo", 10)
                    continue
                if not self.music_deck:
                    self.music_deck = paths.copy()
                    random.shuffle(self.music_deck)
                path = self.music_deck.pop()
                d = media.duration(path)
                self.log("Musik utuh mulai: "+Path(path).name)
                self.decode(path, "music.fifo", ["ffmpeg", "-v", "error", "-nostdin", "-re", "-i", path,
                            "-vn", "-af", "aresample=48000", "-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:1"])
                self.log("Musik selesai; lanjut track berikutnya.")
            except Exception as exc:
                if self.stopping():
                    break
                self.log("Music fallback hening: "+str(exc))
                if not self.output_ready.is_set():
                    continue
                try:
                    self.silence("music.fifo", 5)
                except Exception:
                    time.sleep(1)

    def next_video(self):
        opening = self.cfg.get("opening")
        if opening and not self.cfg.get("_opening_done"):
            self.cfg["_opening_done"] = True
            return store.asset_path(opening)
        paths = [store.asset_path(a) for a in self.cfg["videos"]]
        if not self.video_deck:
            self.video_deck = paths.copy()
            random.shuffle(self.video_deck)
            if len(paths) > 1 and self.video_deck[-1] == self.last_video:
                self.video_deck[0], self.video_deck[-1] = self.video_deck[-1], self.video_deck[0]
        path = self.video_deck.pop()
        self.last_video = path
        return path

    def video_loop(self):
        vf = media.video_filter(self.width, self.height, self.fps, False)
        while not self.stopping():
            if not self.output_ready.wait(.2):
                continue
            path = None
            try:
                path = self.next_video()
                info = media.probe(path)
                d = float(info.get("format", {}).get("duration") or 0)
                if d <= 0:
                    raise ValueError("Durasi video tidak diketahui")
                audio = any(s["codec_type"] == "audio" for s in info["streams"]) and self.cfg.get("original_audio", True)
                af = self.folder / "original-errors.log"
                aargs = (["ffmpeg", "-v", "error", "-nostdin", "-re", "-i", path, "-vn", "-t", f"{d:.3f}",
                          "-af", "apad,aresample=48000", "-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:1"] if audio else
                         ["ffmpeg", "-v", "error", "-nostdin", "-re", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                          "-t", f"{d:.3f}", "-f", "s16le", "pipe:1"])
                audio_errors = []
                def feed_audio():
                    try:
                        self.decode(path, "original.fifo", aargs)
                    except Exception as exc:
                        audio_errors.append(str(exc))
                feeder = threading.Thread(target=feed_audio, daemon=True)
                feeder.start()
                self.log("Video mulai: "+Path(path).name+(" + audio asli" if audio else " + fallback hening"))
                self.decode(path, "video.fifo", ["ffmpeg", "-v", "error", "-nostdin", "-re", "-i", path,
                            "-an", "-vf", vf, "-t", f"{d:.3f}", "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1"])
                feeder.join(timeout=20)
                if audio_errors and not self.stopping():
                    self.log("Audio klip gagal; klip berikutnya memakai fallback: "+audio_errors[-1])
            except Exception as exc:
                if self.stopping():
                    break
                self.log("Video gagal, lewati: "+str(exc))
                try:
                    self.decode(None, "video.fifo", ["ffmpeg", "-v", "error", "-re", "-f", "lavfi", "-i",
                                f"color=c=0x142237:s={self.width}x{self.height}:r={self.fps}", "-t", "2",
                                "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1"])
                    self.silence("original.fifo", 2)
                except Exception:
                    time.sleep(1)

    def prepare_metadata(self):
        if self.cfg.get("metadata"):
            return self.cfg["metadata"]
        if not self.cfg.get("auto_metadata", False):
            return {"title": self.cfg.get("name", f"Live {self.slot}"), "description": "Playlist dari Library.", "hashtags": []}
        paths = [store.asset_path(a) for a in self.cfg.get("audio", [])[:3]]
        if not paths:
            paths = [store.asset_path(a) for a in self.cfg["videos"][:3] if media.has_audio(store.asset_path(a))]
        evidence = media.analyze_audio(paths, self.folder/"analysis") if paths else {"method": "Tidak ada audio; hanya judul berkas", "tracks": []}
        # Spectrogram image is persisted for the user; numeric evidence is sent to the text model.
        public = json.loads(json.dumps(evidence))
        for t in public.get("tracks", []):
            t.pop("spectrogram", None)
        research = ai.web_research(self.cfg.get("topic", "musik playlist Indonesia"), "live", self.account)
        spectrograms = [t["spectrogram"] for t in evidence.get("tracks", []) if Path(t.get("spectrogram", "")).is_file()]
        meta = ai.metadata(self.cfg.get("topic", "Playlist Library"), {"audio_analysis": public, "research": research}, live=True, images=spectrograms)
        desc = meta.get("description", "")+"\n\n"+ " ".join(meta.get("hashtags", []))
        meta["description"] = desc[:4900]
        store.kv_set(f"live-meta-{self.slot}", {"metadata": meta, "analysis": evidence, "research": research})
        return meta

    def run(self):
        for name in ("video.fifo", "music.fifo", "original.fifo"):
            os.mkfifo(self.folder/name, 0o600)
        meta = self.prepare_metadata()
        targets = live.manual_targets(self.cfg.get("manual_rtmp", ""))
        if self.account:
            self.info = youtube.create_live(self.account, meta, self.cfg.get("privacy", "private"),
                                             "720p", self.fps)
            self.broadcast = self.info["broadcast_id"]
            live.update(self.slot, broadcast_id=self.broadcast)
            targets.insert(0, self.info["url"])
        args = live.ffmpeg_command(self.folder, self.width, self.height, self.fps,
                                   int(self.cfg.get("bitrate", 2500)), targets,
                                   float(self.cfg.get("music_volume", .35)), float(self.cfg.get("original_volume", .8)))
        threads = [threading.Thread(target=self.video_loop, daemon=True), threading.Thread(target=self.music_loop, daemon=True)]
        for t in threads:
            t.start()
        failures = 0
        while not self.stopping():
            started = time.time()
            self.main = self.spawn(args)
            self.output_ready.set()
            live.update(self.slot, status="running" if failures == 0 else "reconnecting", heartbeat=time.time())
            self.log("FFmpeg mulai; tujuan="+str(len(targets))+"; musik PCM independen.")
            if self.account and self.info:
                def activate():
                    try:
                        youtube.wait_live(self.account, self.info, self.stopping)
                        self.log("YouTube testing → live berhasil.")
                    except Exception as exc:
                        self.fatal = str(exc)
                        self.stop_event.set()
                threading.Thread(target=activate, daemon=True).start()
            stderr_lines = []
            def drain_main():
                for line in self.main.stderr:
                    msg = redact(line.decode(errors="replace").rstrip())
                    stderr_lines.append(msg)
                    del stderr_lines[:-20]
                    if any(w in msg.lower() for w in ("error", "failed", "broken", "timeout")):
                        self.log(msg)
            drainer = threading.Thread(target=drain_main, daemon=True)
            drainer.start()
            while self.main.poll() is None and not self.stopping():
                live.update(self.slot, heartbeat=time.time())
                time.sleep(1)
            if self.stopping():
                break
            code = self.main.returncode
            self.output_ready.clear()
            self.kill(self.main)
            self.main = None
            # Close ALL old decoders before opening a new generation of FIFO writers.
            # Otherwise a reconnect could interleave bytes from two video feeders.
            with self.guard:
                old_children = list(self.children)
            for child in old_children:
                self.kill(child)
            time.sleep(.3)
            failures = failures+1 if time.time()-started < 600 else 1
            self.log(f"FFmpeg berhenti ({code}); reconnect {failures}. "+" ".join(stderr_lines[-3:]))
            if failures >= 8:
                raise RuntimeError("Delapan reconnect pendek gagal. Slot dihentikan agar tidak melakukan spam koneksi.")
            live.update(self.slot, status="reconnecting", error="Koneksi output terputus; mencoba reconnect.")
            time.sleep(min(60, 2**min(failures, 6)))
            if self.account and self.info:
                try:
                    youtube.wait_live(self.account, self.info, self.stopping, timeout=45)
                except Exception as exc:
                    self.log(str(exc))
        if self.fatal:
            raise RuntimeError(self.fatal)
        if not self.stop_event.is_set():
            self.stopping()

    def cleanup(self):
        self.stop_event.set()
        self.kill(self.main)
        with self.guard:
            children = list(self.children)
        for p in children:
            self.kill(p)
        if self.account and self.broadcast:
            youtube.complete_live(self.account, self.broadcast)
        # Keep small analysis artifacts; remove only this run's FIFOs.
        for p in self.folder.glob("*.fifo"):
            p.unlink(missing_ok=True)


def main():
    import sys
    global _ACTIVE_WORKER
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    slot, run_token = int(sys.argv[1]), sys.argv[2]
    store.init()
    with (RUN/f"live-{slot}.lock").open("w") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        row = store.one("SELECT * FROM lives WHERE slot=?", (slot,))
        if not row or row["run_token"] != run_token or row["stop_requested"]:
            return
        live.update(slot, pid=os.getpid(), heartbeat=time.time())
        worker = Supervisor(slot, run_token)
        _ACTIVE_WORKER = worker
        status, error = "stopped", ""
        try:
            worker.run()
        except Exception as exc:
            status, error = "error", redact(str(exc))
            worker.log(error)
        finally:
            try:
                worker.cleanup()
            except Exception as exc:
                worker.log("Cleanup: "+str(exc))
            live.update(slot, status=status, error=error, pid=0, heartbeat=time.time(), stop_requested=0)


if __name__ == "__main__":
    main()