import io
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import requests
import pytest
from studio import store, youtube


def test_local_resumable_real_http(appdata,sample,monkeypatch):
    import upload_server
    server=ThreadingHTTPServer(("127.0.0.1",0),upload_server.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f"http://127.0.0.1:{server.server_port}"
    headers={"Authorization":"Bearer "+upload_server.upload_token()}
    try:
        raw=Path(store.asset_path(sample["image"])).read_bytes()
        assert requests.get(base+"/api/session/nope").status_code==401
        r=requests.post(base+"/api/session",headers=headers,json={"name":"resume.png","size":len(raw)})
        assert r.status_code==201
        sid=r.json()["id"]; url=base+"/api/session/"+sid
        cut=len(raw)//2
        assert requests.patch(url,headers={**headers,"Upload-Offset":"0"},data=raw[:cut]).json()["offset"]==cut
        assert requests.get(url,headers=headers).json()["offset"]==cut
        assert requests.patch(url,headers={**headers,"Upload-Offset":"0"},data=raw[:cut]).status_code==409
        r=requests.patch(url,headers={**headers,"Upload-Offset":str(cut)},data=raw[cut:])
        assert r.status_code == 200, r.text
        assert r.json()["complete"]
        assert store.asset(r.json()["asset"]["id"])["bytes"]==len(raw)
        from studio.downloads import download_url
        monkeypatch.setenv("UPLOAD_PUBLIC_URL",base)
        link=download_url(sample["image"]["id"])
        assert requests.get(link).content==Path(store.asset_path(sample["image"])).read_bytes()
    finally:
        server.shutdown();server.server_close()


class FakeResponse:
    def __init__(self,status,data=None,headers=None):
        self.status_code=status;self._data=data or {};self.headers=headers or {}
        self.ok=200<=status<300;self.content=b"{}"
    def json(self):return self._data


def test_google_8mib_resume(monkeypatch,appdata,sample):
    size= youtube.UPLOAD_CHUNK+123
    received=bytearray();puts=[]
    monkeypatch.setattr(youtube,"access_token",lambda *a,**k:"test-token")
    def post(url,**kw):return FakeResponse(201,headers={"Location":"https://www.googleapis.com/upload/session"})
    def put(url,**kw):
        rg=kw["headers"]["Content-Range"];puts.append(rg)
        if rg.startswith("bytes */"):
            return FakeResponse(308,headers={"Range":f"bytes 0-{len(received)-1}"}) if received else FakeResponse(308)
        start=int(rg.split()[1].split("-")[0]);data=kw["data"]
        assert start==len(received)
        assert len(data)<=8*1024**2
        received.extend(data)
        if len(received)==size:return FakeResponse(201,{"id":"VIDEO123"})
        return FakeResponse(308,headers={"Range":f"bytes 0-{len(received)-1}"})
    monkeypatch.setattr(youtube.requests,"post",post);monkeypatch.setattr(youtube.requests,"put",put)
    a=dict(sample["video"]);a["id"]="large-test";a["sha256"]="fake"
    p=Path(store.asset_path(sample["video"]))
    # Create a sparse file under isolated data, register separately.
    large=appdata/"library"/"large.mp4"
    with large.open("wb") as f:f.truncate(size)
    a=store.register(large,"large.mp4",sha256="fake")
    meta={"title":"Test","privacy":"private"}
    result=youtube.upload_video("account",a,meta,"job1")
    assert result["video_id"]=="VIDEO123"
    assert puts==[f"bytes 0-{youtube.UPLOAD_CHUNK-1}/{size}",f"bytes {youtube.UPLOAD_CHUNK}-{size-1}/{size}"]
    assert youtube.upload_video("account",a,meta,"job2")["video_id"]=="VIDEO123"
    assert len(puts)==2


def test_oauth_pkce_binding(monkeypatch,appdata):
    monkeypatch.setenv("GOOGLE_CLIENT_ID","client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET","secret")
    url=youtube.begin_auth("a"*64)
    assert "code_challenge_method=S256" in url and "redirect1x.streamlit.app" in url
    from urllib.parse import urlparse,parse_qs
    state=parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(ValueError,match="sesi browser lain"):
        youtube.finish_auth("https://relay/?code=abc&state="+state,"b"*64)
    with pytest.raises(ValueError,match="sudah dipakai"):
        youtube.finish_auth("https://relay/?code=abc&state="+state,"a"*64)