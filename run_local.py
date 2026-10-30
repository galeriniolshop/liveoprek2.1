#!/usr/bin/env python3
"""Start Studio 8501, resumable uploader 8502 and one persistent queue worker."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("LIVEOPREK_DATA", str(ROOT/"data"))
os.environ["AUTO_START_WORKER"] = "false"
children = []
try:
    for name, args in [
        ("worker", [sys.executable, "-m", "studio.worker"]),
        ("uploader", [sys.executable, "upload_server.py", "--port", "8502"]),
        ("studio", [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", "8501"]),
    ]:
        print("Memulai", name, flush=True)
        children.append(subprocess.Popen(args, cwd=ROOT))
    print("Studio: http://localhost:8501\nUploader: http://localhost:8502\nCtrl+C menghentikan semuanya.", flush=True)
    while all(p.poll() is None for p in children):
        time.sleep(1)
finally:
    for p in children:
        if p.poll() is None:
            p.terminate()
    for p in children:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()