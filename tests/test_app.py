import os
from pathlib import Path
import pytest


def test_all_tabs_and_modes(appdata,monkeypatch):
    monkeypatch.setenv("AUTO_START_WORKER","false")
    monkeypatch.setenv("ALLOW_PUBLIC_ACCESS","true")
    monkeypatch.setenv("APP_PASSWORD","")
    monkeypatch.delenv("OLLAMA_API_KEY",raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID",raising=False)
    from streamlit.testing.v1 import AppTest
    root=Path(__file__).resolve().parents[1]
    at=AppTest.from_file(str(root/"app.py"),default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs)==7
    for label in ["B · Reaction Warga +62","Kirim / Upload hasil","A · Kartu kata / puisi"]:
        at.radio(key="shorts_mode").set_value(label).run()
        assert not at.exception,[e.value for e in at.exception]
    for label in ["Upload browser biasa","Unduh URL · yt-dlp + Deno"]:
        at.radio(key="import_mode").set_value(label).run()
        assert not at.exception,[e.value for e in at.exception]


def test_password_gate(appdata,monkeypatch):
    monkeypatch.setenv("APP_PASSWORD","test-password")
    monkeypatch.setenv("AUTO_START_WORKER","false")
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"),default_timeout=30).run()
    assert not at.exception
    assert len(at.tabs)==0
    at.text_input[0].set_value("test-password")
    at.button[0].click().run()
    assert len(at.tabs)==7