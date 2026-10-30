import os
from pathlib import Path
import tempfile
import pytest

@pytest.fixture()
def appdata(tmp_path, monkeypatch):
    from studio import config, store
    from pathlib import Path
    paths = {"DATA":tmp_path, "LIBRARY":tmp_path/"library", "WORK":tmp_path/"work", "LOGS":tmp_path/"logs",
             "RUN":tmp_path/"run", "INCOMING":tmp_path/"incoming", "ANALYSIS":tmp_path/"analysis", "DB":tmp_path/"test.sqlite3"}
    import sys
    for name, p in paths.items():
        monkeypatch.setattr(config, name, p)
        for module in list(sys.modules.values()):
            if module and getattr(module, "__name__", "").startswith("studio.") and hasattr(module, name):
                monkeypatch.setattr(module, name, p, raising=False)
    for p in paths.values():
        if p.suffix != ".sqlite3":
            p.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APP_SECRET", "test-secret-only-012345678901234567890123456789")
    monkeypatch.setenv("UPLOAD_TOKEN", "test-upload-token-01234567890123456789")
    store.init()
    return tmp_path


@pytest.fixture()
def sample(appdata):
    from studio import media, store
    folder = appdata/"fixtures"
    folder.mkdir()
    video, audio, image = folder/"sample.mp4", folder/"sample.m4a", folder/"sample.png"
    media.ffmpeg(["-f","lavfi","-i","testsrc2=size=320x240:rate=15","-f","lavfi","-i","sine=frequency=440:sample_rate=48000",
                  "-t","2","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p","-c:a","aac","-shortest",str(video)])
    media.ffmpeg(["-f","lavfi","-i","sine=frequency=660:sample_rate=48000","-t","3","-c:a","aac",str(audio)])
    from PIL import Image
    Image.new("RGB",(360,640),"#24506a").save(image)
    return {"video":store.import_file(video,"sample.mp4",move=False),
            "audio":store.import_file(audio,"sample.m4a",move=False),
            "image":store.import_file(image,"sample.png",move=False)}