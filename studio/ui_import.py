from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import streamlit as st
from . import store, importer
from .config import ROOT, WORK, MAX_ASSET_BYTES, secret, flag
from .ui_common import human


def render():
    st.subheader("Impor ke Library")
    mode = st.radio("Jalur impor", ["Upload lokal resumable · 8502", "Upload browser biasa", "Unduh URL · yt-dlp + Deno"], key="import_mode")
    if mode.startswith("Upload lokal"):
        st.markdown("#### transfer besar, bisa dilanjutkan")
        st.write("Jalankan pendamping di komputer/server yang menyimpan Library:")
        st.code("python upload_server.py --port 8502", language="bash")
        token_path = Path(store.DATA)/"upload.token"
        if token_path.exists():
            with st.expander("Tampilkan token uploader (rahasia)"):
                st.code(token_path.read_text(), language=None)
        st.caption("Buka alamat uploader port 8502, masukkan token, pilih berkas. Kelanjutan memakai ID sesi + offset, termasuk setelah browser ditutup.")
        public_url = secret("UPLOAD_PUBLIC_URL")
        if public_url:
            st.link_button("Buka uploader resumable →", public_url)
        else:
            st.info("Lokal: buka port 8502 pada komputer yang menjalankan aplikasi. Cloud tidak mengekspos port 8502; pakai upload browser atau unggah ke VPS lalu impor.")
        if st.button("Segarkan Library setelah transfer"):
            st.rerun()
    elif mode.startswith("Upload browser"):
        files = st.file_uploader("Video / audio / gambar", type=["mp4","mov","mkv","webm","m4v","avi","ts","mp3","m4a","wav","flac","ogg","opus","aac","jpg","jpeg","png","webp"], accept_multiple_files=True)
        st.caption("Batas per berkas ditentukan server.maxUploadSize (default 200 MiB). Untuk file besar gunakan pendamping 8502.")
        if st.button("Masukkan ke Library", type="primary", disabled=not files):
            bar = st.progress(0.0)
            for idx, f in enumerate(files):
                target = WORK / (uuid.uuid4().hex+Path(f.name).suffix.lower())
                try:
                    if f.size > MAX_ASSET_BYTES:
                        raise ValueError("Berkas terlalu besar.")
                    with target.open("wb") as out:
                        while block := f.read(1024*1024):
                            out.write(block)
                    a = store.import_file(target, f.name, "browser")
                    st.success(a["name"]+" · "+human(a["bytes"]))
                except Exception as e:
                    st.error(f.name+": "+str(e))
                finally:
                    target.unlink(missing_ok=True)
                    bar.progress((idx+1)/len(files))
    else:
        url = st.text_input("URL video / audio publik", placeholder="https://www.youtube.com/watch?v=…", key="import_url")
        audio_only = st.checkbox("Ekstrak audio saja → AAC .m4a", value=False)
        deno = importer.deno_path()
        c1, c2 = st.columns([1, 2])
        c1.write("Deno: "+("tersedia" if deno else "belum tersedia"))
        if c2.button("Siapkan Deno (unduh rilis resmi + cek SHA256)"):
            try:
                with st.spinner("Mengunduh binary Deno yang sesuai arsitektur…"):
                    r = subprocess.run([sys.executable, str(ROOT/"scripts"/"install_deno.py")], capture_output=True, text=True, timeout=240)
                if r.returncode:
                    st.error(r.stderr[-1500:])
                else:
                    st.success(r.stdout[-1000:])
            except Exception as e:
                st.error(str(e))
        st.caption("Default: YouTube, SoundCloud, Vimeo. Hanya untuk konten yang Anda miliki/berizin. Tidak ada bypass DRM/login. Kegagalan ekstraksi dilaporkan, tidak diakali dengan scraping ilegal.")
        if st.button("Antrekan unduh URL", type="primary", disabled=not url):
            try:
                importer.validate_url(url)
                jid = store.enqueue("import_url", "Impor: "+url[:120], {"url": url, "audio_only": audio_only})
                st.success("Masuk antrean: "+jid)
            except Exception as e:
                st.error(str(e))