import json
from pathlib import Path
import pytest
from studio import store, live
from studio.security import encrypt, decrypt, redact


def test_encryption_roundtrip(appdata):
    value = "rahasia_oauth_123"
    assert decrypt(encrypt(value)) == value
    assert value not in encrypt(value)


def test_asset_locks_and_atomic_delete(appdata, sample):
    aid = sample["video"]["id"]
    jid = store.enqueue("normalize_video", "test", {"asset_id":aid}, [aid])
    with pytest.raises(ValueError, match="dipakai"):
        store.delete_asset(aid, True)
    assert Path(store.asset_path(aid)).exists()
    store.update_job(jid,status="done")
    store.unlock("job:"+jid)
    store.delete_asset(aid, True)
    assert not Path(store.asset_path(sample["video"])).exists()


def test_live_playlist_lock(appdata, sample):
    cfg = {"videos":[sample["video"]["id"]],"audio":[sample["audio"]["id"]],"manual_rtmp":"rtmp://example.com/live/key"}
    live.save_config(1,cfg,"Test")
    assert live.config(1) == cfg
    with pytest.raises(ValueError):
        store.delete_asset(sample["audio"]["id"],True)
    assert "rtmp://" not in store.one("SELECT vault FROM lives WHERE slot=1")["vault"]
    store.unlock("live:1")
    store.delete_asset(sample["audio"]["id"],True)


def test_path_escape(appdata):
    with pytest.raises(ValueError):
        store.safe_path("/etc/passwd")
    with pytest.raises(ValueError):
        store.safe_path(appdata/"../escape")


def test_tee_and_redaction():
    s = live.tee_destination(["rtmps://a.live.youtube.com:443/rtmp/key?foo=a,b","rtmp://example.com/live/secret"])
    assert s.count("onfail=ignore") == 2
    assert "\\:" in s and "\\," in s
    assert "[STREAM_KEY]" in redact("Output rtmp://example.com/live/secret failed")
    assert "abc123" not in redact("https://example.com/?access_token=abc123&x=1")


def test_url_ssrf():
    from studio.importer import validate_url
    with pytest.raises(ValueError):
        validate_url("http://127.0.0.1/a.mp4")
    with pytest.raises(ValueError):
        validate_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_url("https://youtube.com@127.0.0.1/a")