from __future__ import annotations
import gc
import hmac
import os
from pathlib import Path
import shutil
import time
import streamlit as st
import streamlit.components.v1 as components
from studio import store, worker, live, youtube, clipdrop, ai, media
from studio.config import ROOT, DATA, LIBRARY, WORK, INCOMING, ensure_dirs, secret, flag
from studio.ui_common import human

st.set_page_config(page_title="Studio Render & Live · liveoprek2", page_icon="◉", layout="wide", initial_sidebar_state="expanded")
ensure_dirs()
store.init()

st.markdown("""<style>
.stApp{background:#0b1320;color:#e7eef9}.block-container{padding-top:2rem}h1,h2,h3{letter-spacing:-.035em}
[data-testid="stSidebar"]{background:#101d2e;border-right:1px solid #23364d}
[data-testid="stExpander"]{border:1px solid #2b3d54;border-radius:12px;background:#111e30}
.stButton>button,.stDownloadButton>button{border-radius:8px;border:1px solid #405572}
.stButton>button[kind="primary"]{background:#f4b860;color:#142238;border:0;font-weight:750}
.stTabs [data-baseweb="tab-list"]{gap:5px;flex-wrap:wrap}.stTabs [data-baseweb="tab"]{font-weight:650}
[data-testid="stMetric"]{background:#142237;padding:15px;border-radius:12px;border:1px solid #293e58}
small,.stCaption{color:#a6b7ce!important}a{color:#f4b860!important}
.hero{padding:25px 28px;border:1px solid #34485f;border-radius:18px;background:linear-gradient(115deg,#172c43,#122033 65%,#34302a);margin-bottom:22px}
.eyebrow{font-size:11px;letter-spacing:.22em;color:#78d5c0;font-weight:750}.hero h1{margin:8px 0;font-size:38px}.hero p{color:#b8c8dc;margin:0}
</style><div class="hero"><div class="eyebrow">LIVEOPREK2 / CREATOR OPERATIONS</div><h1>Studio Render &amp; Live</h1><p>Dari satu berkas menjadi Shorts. Dari satu playlist menjadi siaran.</p></div>""", unsafe_allow_html=True)

password = secret("APP_PASSWORD")
if password:
    if not st.session_state.get("authenticated"):
        st.info("Studio ini bersifat single-admin. Masuk untuk mengakses media, akun, dan kontrol siaran.")
        with st.form("login"):
            supplied = st.text_input("Password studio", type="password")
            if st.form_submit_button("Masuk"):
                if hmac.compare_digest(supplied.encode(), password.encode()):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    time.sleep(1)
                    st.error("Password tidak cocok.")
        st.stop()
elif (youtube.configured() or ai.configured()) and not flag("ALLOW_PUBLIC_ACCESS"):
    st.error("Keamanan: APP_PASSWORD wajib diisi sebelum memakai kunci API/OAuth pada deployment publik. "
             "Untuk uji lokal saja, ALLOW_PUBLIC_ACCESS=true dapat mengizinkan akses tanpa password.")
    st.stop()
else:
    st.sidebar.warning("Mode tanpa password. Pakai hanya di komputer lokal/private.")

with st.sidebar:
    st.markdown("### ◉ liveoprek2")
    st.caption("Satu workspace bersama untuk satu operator/tim tepercaya.")
    if st.button("Segarkan status", use_container_width=True):
        st.rerun()
    if st.button("Keluar", disabled=not password, use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    st.divider()
    st.markdown("**Deployment**")
    deployment = secret("DEPLOYMENT_MODE", "local")
    st.write("VPS / lokal" if deployment != "cloud" else "Streamlit Cloud")
    st.caption("Data: "+str(DATA))
    st.markdown("**Dokumentasi**")
    if Path(ROOT/"README.md").exists():
        with open(ROOT/"README.md", "rb") as f:
            st.download_button("Panduan README", f, file_name="README-liveoprek2.md")
    st.caption("Baca batas Cloud, lisensi konten, OAuth, dan biaya API sebelum penggunaan publik.")


def handle_clipdrop():
    """Consume query credentials before rendering. Never assign key to session_state or payload."""
    if "cdk" not in st.query_params:
        return
    key = st.query_params.get("cdk")
    prompt = st.query_params.get("cd_prompt", "Vertical cinematic landscape, no text")
    effect = st.query_params.get("cd_effect", "rain")
    seconds = st.query_params.get("cd_duration", "15")
    music_id = st.query_params.get("cd_music", "")
    nonce = st.query_params.get("cd_nonce", "")
    for k in ("cdk", "cd_prompt", "cd_effect", "cd_duration", "cd_music", "cd_nonce"):
        st.query_params.pop(k, None)
    try:
        if not nonce or store.kv_get("clipdrop-nonce") == nonce:
            raise ValueError("Request kosong/sudah digunakan. Kirim formulir baru.")
        store.kv_set("clipdrop-nonce", nonce)
        effect = effect if effect in {"rain", "petals", "snow", "embers"} else "rain"
        seconds = max(5, min(60, float(seconds)))
        music_ids = [music_id] if music_id and store.one("SELECT id FROM assets WHERE id=? AND kind='audio'", (music_id,)) else []
        with st.spinner("Membuat gambar Clipdrop; kunci tidak masuk antrean…"):
            image_path = clipdrop.generate(prompt, key)
        try:
            asset = store.import_file(image_path, "Clipdrop · "+prompt[:70]+".png", "clipdrop")
        finally:
            image_path.unlink(missing_ok=True)
        jid = store.enqueue("clipdrop_motion", "Clipdrop → Video", {"image_id": asset["id"], "music_ids": music_ids,
                            "effect": effect, "seconds": seconds, "resolution": "1080p"}, [asset["id"]]+music_ids)
        st.session_state.last_clipdrop_job = jid
        st.success("Latar tersalin ke Library. Render MP4 masuk antrean: "+jid)
    except Exception as exc:
        # Do not str() arbitrary HTTP exceptions that could contain request headers.
        message = str(exc)
        if key:
            message = message.replace(key, "[REDACTED]")
        st.error(message[:1000])
    finally:
        key = prompt = nonce = None
        del key, prompt, nonce
        gc.collect()


handle_clipdrop()
# OAuth callback is consumed on arrival. Browser binding is verified by the OAuth panel.
if "code" in st.query_params and "state" in st.query_params:
    callback = "https://studio.local/?"+"code="+st.query_params["code"]+"&state="+st.query_params["state"]
    st.query_params.pop("code", None)
    st.query_params.pop("state", None)
    st.query_params.pop("scope", None)
    try:
        channels = youtube.finish_auth(callback, st.session_state.get("oauth_browser", ""))
        st.success("Channel terhubung: "+", ".join(a["title"] for a in channels))
    except Exception:
        st.info("Callback diterima pada sesi baru. Untuk keamanan, mulai OAuth lagi lalu tempel callback lengkap pada sesi yang sama.")
    finally:
        callback = None
        del callback
        gc.collect()

if "w" not in st.session_state:
    try:
        st.session_state.w = worker.ensure_worker()
    except Exception as e:
        st.sidebar.error(str(e))

tabs = st.tabs(["Library", "Impor", "Clipdrop → Video", "Viral Shorts", "Normalisasi & Tes", "Live 24 Jam", "Job & Disk"])
with tabs[0]:
    from studio.ui_library import render
    render()
with tabs[1]:
    from studio.ui_import import render
    render()
with tabs[2]:
    st.subheader("Clipdrop → Video")
    st.caption("Satu request gambar berbayar/berkuota, lalu render lokal FFmpeg. Kunci tidak disimpan di database, berkas, log, atau payload job.")
    if st.session_state.get("last_clipdrop_job"):
        st.info("Job terakhir: "+st.session_state.last_clipdrop_job)
    st.iframe(clipdrop.request_html(store.assets("audio")), height=675)
    st.info("Privasi: query parameter tetap dapat terlihat oleh infrastruktur/proxy dan riwayat browser. Aplikasi membersihkan URL dan referensi kunci, tetapi tidak dapat menjanjikan penghapusan forensik RAM Python. Untuk isolasi penuh, gunakan deployment privat.")
with tabs[3]:
    from studio.ui_shorts import render
    render()
with tabs[4]:
    from studio.ui_normalize import render
    render()
with tabs[5]:
    from studio.ui_live import render
    st.fragment(run_every=8)(render)()
with tabs[6]:
    from studio.ui_jobs import render
    st.fragment(run_every=4)(render)()