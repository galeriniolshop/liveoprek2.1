from pathlib import Path
import json
import pytest
from studio import media, render


def test_probe_and_loudness(appdata,sample,tmp_path):
    assert media.has_audio(store_path(sample["video"]))
    out = tmp_path/"norm.m4a"
    media.normalize_audio(store_path(sample["audio"]),out,target=-16)
    info=media.probe(out)
    a=next(s for s in info["streams"] if s["codec_type"]=="audio")
    assert a["codec_name"]=="aac" and a["sample_rate"]=="48000" and a["channels"]==2
    measured=media.loudnorm_measure(out)
    assert abs(float(measured["input_i"])+16)<1.5


def store_path(a):
    from studio.store import asset_path
    return asset_path(a)


def test_motion_all_effects(appdata,sample):
    draft={"ribbon":"TETAP PULANG","lines":["Ada jalan yang panjang.","Ada hati yang tetap pulang."],"signature":"ruang miring"}
    for effect in ("rain","petals","snow","embers"):
        out=appdata/(effect+".mp4")
        render.motion_video(store_path(sample["image"]),str(out),appdata/effect,effect,5,
                            store_path(sample["audio"]),draft,360,640)
        info=media.probe(out)
        v=next(s for s in info["streams"] if s["codec_type"]=="video")
        assert v["codec_name"]=="h264" and (v["width"],v["height"])==(360,640)
        assert media.has_audio(out)
        assert 4.9<media.duration(out)<5.3


def test_reaction_ducking_and_subtitles(appdata,sample):
    segments=[{"text":"Wah, kok bisa begitu, warga?","start":.6,"end":2.5},
              {"text":"Aku perlu waktu buat mencerna ini.","start":2.72,"end":4.7}]
    narration=appdata/"narration.wav"
    media.ffmpeg(["-f","lavfi","-i","sine=frequency=800:sample_rate=48000","-t","5","-ac","2","-c:a","pcm_s16le",str(narration)])
    out=appdata/"reaction.mp4"
    render.reaction_video(store_path(sample["video"]),str(out),appdata/"reaction","REAKSI WARGA",str(narration),segments,5,360,640)
    assert media.probe(out)["streams"]
    assert "Dialogue:" in (appdata/"reaction"/"reaction.ass").read_text()
    assert media.duration(out) >= 4.9  # ducking graph exercised by successful real FFmpeg render


def test_spectral_analysis(appdata,sample):
    from studio.store import asset_path
    result=media.analyze_audio([asset_path(sample["audio"])],appdata/"analysis")
    assert result["tracks"][0]["spectral_centroid_hz"]>0
    assert Path(result["tracks"][0]["spectrogram"]).exists()


def test_subtitle_generation():
    text=render.srt_text([{"text":"Halo warga","start":.6,"end":2.35}])
    assert "00:00:00,600 --> 00:00:02,350" in text
    assert render.ass_time(61.23)=="0:01:01.23"