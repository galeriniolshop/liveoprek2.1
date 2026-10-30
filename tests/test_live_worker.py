"""Real RTMP loopback integration: no YouTube account or external network needed."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import pytest
from studio import store, live, media
from studio.live_worker import Supervisor


def test_live_rtmp_three_pipes(appdata,sample,monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    port=19350
    output=appdata/"received.flv"
    receiver=subprocess.Popen(["ffmpeg","-v","error","-nostdin","-listen","1","-i",f"rtmp://127.0.0.1:{port}/live/test",
                               "-t","7","-c","copy","-f","flv",str(output)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        time.sleep(.5)
        cfg={"videos":[sample["video"]["id"]],"audio":[sample["audio"]["id"]],
             "manual_rtmp":f"rtmp://127.0.0.1:{port}/live/test","fps":24,"bitrate":800,
             "vertical":False,"original_audio":True}
        live.save_config(1,cfg,"Loopback")
        # Allow only this test's known loopback endpoint; production validator also accepts it.
        token="test-"+__import__("uuid").uuid4().hex
        live.update(1,run_token=token,status="starting",heartbeat=time.time())
        worker=Supervisor(1,token)
        thread=threading.Thread(target=worker.run,daemon=True)
        thread.start()
        time.sleep(9)
        if thread.is_alive():
            worker.log("Test heartbeat")
        else:
            print("Worker exited early")
        worker.stop_event.set()
        worker.cleanup()
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert output.exists() and output.stat().st_size>10000, receiver.stderr.read().decode() if receiver.poll() is not None else "receiver still running"
        info=media.probe(output)
        assert {s["codec_type"] for s in info["streams"]} == {"video","audio"}
    finally:
        if receiver.poll() is None:
            receiver.terminate()
        try: receiver.wait(timeout=5)
        except subprocess.TimeoutExpired: receiver.kill()
        receiver.stdout.close();receiver.stderr.close()


def test_six_slots_independent(appdata,sample):
    cfg={"videos":[sample["video"]["id"]],"audio":[sample["audio"]["id"]],"manual_rtmp":"rtmp://example.com/live/key"}
    for slot in range(1,7):
        live.save_config(slot,cfg,f"Slot {slot}")
        assert live.config(slot)["videos"]==cfg["videos"]
        assert live.state(slot)["status"]=="stopped"
    assert len(store.rows("SELECT * FROM refs WHERE owner LIKE 'live:%'"))==12