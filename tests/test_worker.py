import json
from pathlib import Path
from studio import store,worker,media


def test_poem_job_real_render(appdata,sample):
    draft={"ribbon":"INI RUANG KITA","lines":["Pelan pelan, kita bertumbuh."],"signature":"ruang miring",
           "title":"Ruang Bertumbuh","description":"Puisi orisinal.","hashtags":["#Shorts"],"tags":["puisi"]}
    jid=store.enqueue("poem","Poem job",{"image_id":sample["image"]["id"],"music_ids":[sample["audio"]["id"]],
                      "draft":draft,"seconds":5,"resolution":"720p","effect":"snow"},[sample["image"]["id"],sample["audio"]["id"]])
    worker.execute(store.job(jid))
    j=store.job(jid)
    assert j["status"]=="done"
    a=store.asset(j["result"]["asset_id"])
    assert a["kind"]=="video"
    v=next(s for s in media.probe(store.asset_path(a))["streams"] if s["codec_type"]=="video")
    assert (v["width"],v["height"])==(720,1280)


def test_reaction_job_local_tts(appdata,sample,monkeypatch):
    # Deterministic offline TTS adapter; Edge TTS was separately smoke-tested online.
    from studio import tts
    def local_synth(lines,folder,*args,**kwargs):
        result=[]
        for i,line in enumerate(lines):
            p=folder/f"local-{i}.wav"
            media.ffmpeg(["-f","lavfi","-i","sine=frequency=440:sample_rate=48000","-t","0.4","-c:a","pcm_s16le",str(p)])
            result.append({"text":line,"path":str(p),"duration":0.4})
        return result
    monkeypatch.setattr(tts,"synthesize",local_synth)
    draft={"banner":"ADA YANG ANEH","lines":["Wah, kok bisa begitu, warga?","Coba lihat lagi deh."],
           "title":"Reaksi seru","description":"Reaction contoh.","hashtags":["#Shorts"],"tags":["reaction"]}
    jid=store.enqueue("reaction","Reaction job",{"source_id":sample["video"]["id"],"seconds":10,"draft":draft,"resolution":"720p"},[sample["video"]["id"]])
    worker.execute(store.job(jid))
    j=store.job(jid)
    assert j["status"]=="done",j["error"]
    assert Path(j["result"]["srt"]).is_file()
    assert media.has_audio(store.asset_path(j["result"]["asset_id"]))


def test_cancel_media_process(appdata):
    import threading,time
    cancelled=threading.Event()
    threading.Timer(.3, cancelled.set).start()
    import pytest
    with pytest.raises(media.Cancelled):
        media.ffmpeg(["-f","lavfi","-i","sine=frequency=440","-f","null","-"],cancel=cancelled.is_set,timeout=10)