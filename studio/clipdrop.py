"""One-shot browser URL hand-off. Never persist the Clipdrop key in jobs/database."""
from __future__ import annotations
import gc
import json
from pathlib import Path
import requests
from .config import WORK
from .media import check_cancel


def generate(prompt: str, key: str, cancel=None) -> Path:
    if not key or len(key) > 512:
        raise ValueError("Kunci Clipdrop tidak valid.")
    check_cancel(cancel)
    output = WORK / ("clipdrop-" + __import__("uuid").uuid4().hex + ".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    headers = {"x-api-key": key}
    response = None
    try:
        response = requests.post("https://clipdrop-api.co/text-to-image/v1", headers=headers,
                                 files={"prompt": (None, prompt[:1000], "text/plain")},
                                 timeout=(15, 150), stream=True)
        if not response.ok:
            # Never echo provider bodies, which may reflect authentication information.
            raise RuntimeError(f"Clipdrop menolak request (HTTP {response.status_code}). Periksa kunci/kuota/prompt.")
        if not response.headers.get("Content-Type", "").startswith("image/"):
            raise ValueError("Clipdrop tidak mengembalikan gambar.")
        size = 0
        with output.open("wb") as f:
            for block in response.iter_content(65536):
                check_cancel(cancel)
                size += len(block)
                if size > 32 * 1024**2:
                    raise ValueError("Gambar Clipdrop melebihi batas 32 MiB.")
                f.write(block)
        from PIL import Image
        with Image.open(output) as im:
            im.verify()
        return output
    except requests.RequestException:
        output.unlink(missing_ok=True)
        raise RuntimeError("Request Clipdrop gagal/timeout. Kunci tidak disimpan; coba request baru.")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        if response is not None:
            response.close()
        headers.clear()
        del headers, response
        gc.collect()


def request_html(music_options: list[dict]) -> str:
    options = "".join(f'<option value="{a["id"]}">{__import__("html").escape(a["name"][:70])}</option>' for a in music_options)
    return """<!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{font:14px system-ui;margin:0;color:#e8eef7;background:#111b2a}
    .box{padding:20px;border:1px solid #33435a;border-radius:14px}label{display:block;margin:12px 0 6px;color:#b9c9dc}
    input,textarea,select{width:100%;padding:11px;border:1px solid #40536c;border-radius:8px;background:#0b1320;color:white}
    textarea{height:90px}button{margin-top:16px;background:#f4b860;color:#172235;border:0;border-radius:8px;padding:12px 18px;font-weight:750;cursor:pointer}
    .row{display:flex;gap:12px}.row>div{flex:1}small{color:#a7b6cb;line-height:1.5}#status{margin-top:10px}
    </style></head><body><form class="box" id="f"><label>Prompt gambar (tanpa tulisan)</label>
    <textarea id="prompt" maxlength="1000" required>Vertical cinematic Indonesian mountain lake at dawn, warm mist, poetic quiet atmosphere, no text, central negative space</textarea>
    <div class="row"><div><label>Efek</label><select id="effect"><option value="rain">Hujan</option><option value="petals">Kelopak bunga</option><option value="snow">Salju</option><option value="embers">Bara api</option></select></div>
    <div><label>Durasi MP4 (detik)</label><input id="duration" type="number" min="5" max="60" value="15"></div></div>
    <label>Musik Library</label><select id="music"><option value="">Tanpa musik / hening</option>__OPTIONS__</select>
    <label>Kunci Clipdrop — satu request, tidak disimpan aplikasi</label><input id="key" type="password" autocomplete="off" maxlength="512" required>
    <small>URL hand-off bersifat sementara. Aplikasi menghapus parameter dan referensi kunci setelah request, tetapi Python/browser tidak menjamin secure RAM erase. Hindari riwayat/proxy yang merekam URL.</small>
    <button type="submit">Buat latar & antrekan video →</button><div id="status"></div></form><script>
    const topWin=window.parent;
    try{const u=new URL(topWin.location.href);let dirty=false;for(const k of ['cdk','cd_prompt','cd_effect','cd_duration','cd_music','cd_nonce']){if(u.searchParams.has(k)){u.searchParams.delete(k);dirty=true}}if(dirty)topWin.history.replaceState({},'',u.toString());}catch(e){}
    document.getElementById('f').onsubmit=function(e){e.preventDefault();const b=document.querySelector('button');b.disabled=true;
      const u=new URL(topWin.location.href);for(const [k,id] of [['cdk','key'],['cd_prompt','prompt'],['cd_effect','effect'],['cd_duration','duration'],['cd_music','music']]){u.searchParams.set(k,document.getElementById(id).value)}
      u.searchParams.set('cd_nonce',crypto.randomUUID());document.getElementById('key').value='';
      document.getElementById('status').textContent='Mengirim request sekali pakai…';topWin.location.href=u.toString();};
    </script></body></html>""".replace("__OPTIONS__", options)