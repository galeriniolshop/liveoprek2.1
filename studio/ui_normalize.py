from __future__ import annotations
import shutil
import subprocess
import streamlit as st
from . import store, media, ai, importer
from .ui_common import choose


def render():
    st.subheader("Normalisasi & Tes")
    st.caption("Dua-pass EBU R128: ukur dahulu, kemudian normalisasi. Audio menjadi AAC .m4a 48 kHz stereo; video menjadi H.264 MP4 + AAC.")
    target = st.slider("Target loudness (LUFS)", -24, -12, -16, key="norm_target")
    st.caption("−16 LUFS untuk musik/library; −14 LUFS umum untuk hasil berisi narasi. True peak dijaga ≤ −1.5 dBTP.")
    kind = st.radio("Jenis normalisasi", ["Audio → AAC .m4a", "Video → H.264 MP4"], horizontal=True)
    audio = kind.startswith("Audio")
    assets = store.assets("audio" if audio else "video")
    selected = choose("Berkas yang akan dinormalisasi", assets, "norm_assets")
    vertical = st.checkbox("Video vertikal 720×1280 (default 1280×720, fit tanpa crop)", value=False) if not audio else False
    if st.button("Antrekan normalisasi", type="primary", disabled=not selected):
        for aid in selected:
            jid = store.enqueue("normalize_audio" if audio else "normalize_video", "Normalisasi: "+store.asset(aid)["name"],
                                {"asset_id": aid, "target": target, "vertical": vertical}, [aid])
            st.success("Job: "+jid)
    st.divider()
    st.markdown("### Pemeriksaan sistem")
    if st.button("Jalankan tes lingkungan"):
        checks = []
        for name in ("ffmpeg", "ffprobe", "espeak-ng"):
            path = shutil.which(name)
            checks.append({"Komponen": name, "Status": "Tersedia" if path else "Belum ada", "Lokasi": path or "packages.txt"})
        checks.append({"Komponen": "Deno", "Status": "Tersedia" if importer.deno_path() else "Belum ada", "Lokasi": importer.deno_path() or "scripts/install_deno.py"})
        checks.append({"Komponen": "Ollama key", "Status": "Terkonfigurasi" if ai.configured() else "Belum ada", "Lokasi": "Server secrets"})
        checks.append({"Komponen": "Tuliskan data", "Status": "OK" if __import__("os").access(store.DATA, __import__("os").W_OK) else "Gagal", "Lokasi": str(store.DATA)})
        st.table(checks)
        st.caption("Tes ini tidak memanggil API berbayar. Uji render nyata tersedia melalui scripts/smoke_test.py dan pytest.")
    st.info("Hasil kerja tetap berupa berkas baru. Berkas sumber tidak ditimpa. Pantau progres, kegagalan, dan hasil pada tab Job & Disk.")