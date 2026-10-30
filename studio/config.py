"""Configuration; secrets are never written to job payloads or logs."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_setting(name, default):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return str(st.secrets.get(name, default))
    except Exception:
        return default


DATA = Path(_bootstrap_setting("LIVEOPREK_DATA", str(ROOT / "data"))).resolve()
LIBRARY = DATA / "library"
WORK = DATA / "work"
LOGS = DATA / "logs"
RUN = DATA / "run"
INCOMING = DATA / "incoming"
ANALYSIS = DATA / "analysis"
DB = DATA / "studio.sqlite3"
MAX_ASSET_BYTES = int(os.environ.get("MAX_ASSET_BYTES", str(8 * 1024**3)))
UPLOAD_CHUNK = 8 * 1024 * 1024  # Google: 8 MiB, a multiple of 256 KiB.
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".mka"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
REDIRECT_URI = "https://redirect1x.streamlit.app"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/youtube.readonly"]


def secret(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
        if "google" in st.secrets and name.startswith("GOOGLE_"):
            key = name.removeprefix("GOOGLE_").lower()
            return str(st.secrets["google"].get(key, default))
    except Exception:
        pass
    return default


def flag(name: str, default: bool = False) -> bool:
    return secret(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def ensure_dirs() -> None:
    for path in (DATA, LIBRARY, WORK, LOGS, RUN, INCOMING, ANALYSIS):
        path.mkdir(parents=True, exist_ok=True)
    try:
        DATA.chmod(0o700)
    except OSError:
        pass


def asset_kind(suffix: str) -> str:
    s = suffix.lower()
    if s in VIDEO_EXT:
        return "video"
    if s in AUDIO_EXT:
        return "audio"
    if s in IMAGE_EXT:
        return "image"
    raise ValueError("Format tidak didukung. Gunakan video, audio, atau gambar yang dikenal FFmpeg/Pillow.")


def font(name: str = "regular") -> str:
    names = {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf",
             "italic": "DejaVuSans-Oblique.ttf", "serif": "DejaVuSerif.ttf"}
    return str(ROOT / "assets" / "fonts" / names.get(name, names["regular"]))