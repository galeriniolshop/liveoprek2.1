import pytest
from studio import tts,ai


def test_offline_fallback_on_network_failure(appdata,monkeypatch):
    import edge_tts
    def unavailable(*args,**kwargs):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr(edge_tts,"Communicate",unavailable)
    segments=tts.synthesize(["Halo warga, apa kabar?"],appdata/"voice",fallback=True)
    assert segments[0]["duration"]>0
    assert segments[0]["path"].endswith(".wav")


def test_no_silent_fallback(appdata,monkeypatch):
    import edge_tts
    def unavailable(*args,**kwargs):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr(edge_tts,"Communicate",unavailable)
    with pytest.raises(RuntimeError,match="Edge TTS gagal"):
        tts.synthesize(["Halo"],appdata/"voice",fallback=False)


def test_ai_json_and_required_credentials(appdata,monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(ValueError,match="OLLAMA_API_KEY"):
        ai.post("/api/chat",{})
    assert ai.extract_json('```json\n{"title":"Halo"}\n```')["title"]=="Halo"
    with pytest.raises(ValueError):
        ai.extract_json("bukan json")


def test_research_never_invents_views(appdata,monkeypatch):
    monkeypatch.setattr(ai,"post",lambda *a,**k:{"results":[{"title":"Contoh","url":"https://youtube.com/shorts/example","content":"Snippet"}]})
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    result=ai.web_research("topik")
    assert result["references"][0]["views"] is None
    assert "bukan pemeringkatan lengkap" in result["disclaimer"]