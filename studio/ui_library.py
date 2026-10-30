from __future__ import annotations
from pathlib import Path
import streamlit as st
from . import store
from .config import DATA
from .ui_common import human


def render():
    st.subheader("Library media")
    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("Cari nama berkas", key="library_search", placeholder="Judul, musik, latar…")
    kind = c2.selectbox("Jenis", ["all", "video", "audio", "image"], format_func=lambda x: {"all":"Semua", "video":"Video", "audio":"Audio", "image":"Gambar"}[x])
    per_page = c3.selectbox("Per halaman", [12, 24, 48], index=0)
    assets = store.assets(kind, query)
    pages = max(1, (len(assets)+per_page-1)//per_page)
    page = st.number_input("Halaman", 1, pages, 1, key="library_page")
    shown = assets[(page-1)*per_page:page*per_page]
    ids = [a["id"] for a in shown]
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Pilih semua di halaman"):
        for aid in ids:
            st.session_state["asset_"+aid] = True
        st.rerun()
    if b2.button("Kosongkan pilihan"):
        for a in store.assets():
            st.session_state["asset_"+a["id"]] = False
        st.rerun()
    b3.metric("Aset cocok", len(assets))
    b4.metric("Ukuran cocok", human(sum(a["bytes"] for a in assets)))
    selected = []
    for a in shown:
        col1, col2 = st.columns([1, 11])
        with col1:
            if st.checkbox("Pilih "+a["name"], key="asset_"+a["id"], label_visibility="collapsed"):
                selected.append(a["id"])
        with col2:
            refs = store.references(a["id"])
            with st.expander(f"{'🔒' if refs else '○'} {a['name']} · {a['kind']} · {human(a['bytes'])}"):
                p = store.asset_path(a)
                if not Path(p).exists():
                    st.error("Berkas hilang dari disk. Hapus catatan aset setelah konfirmasi.")
                elif a["kind"] == "image":
                    st.image(p, use_container_width=True)
                elif a["kind"] == "video":
                    if a["bytes"] <= 150*1024**2:
                        st.video(p)
                    else:
                        st.info("Preview file besar dinonaktifkan agar RAM aman. Unduh untuk memutar.")
                else:
                    if a["bytes"] <= 60*1024**2:
                        st.audio(p)
                    else:
                        st.info("Preview audio besar dinonaktifkan. Unduh untuk memutar.")
                st.caption(f"ID: {a['id']} · Sumber: {a['origin']}")
                if refs:
                    st.warning("Terkunci: "+", ".join(refs))
                if Path(p).exists() and a["bytes"] <= 200*1024**2:
                    with open(p, "rb") as f:
                        st.download_button("Unduh berkas", f, file_name=a["name"], key="download_"+a["id"])
                elif Path(p).exists():
                    st.info("Berkas >200 MiB: gunakan tombol unduh server di bawah, bukan memuat seluruh file ke RAM Streamlit.")
                if a["metadata"].get("source_url"):
                    st.caption("URL sumber: "+a["metadata"]["source_url"])
    st.divider()
    st.write(f"**{len(selected)} aset dipilih** · penghapusan permanen, bukan tempat sampah.")
    confirm = st.checkbox("Saya yakin ingin menghapus aset terpilih secara permanen", key="lib_delete_confirm")
    if st.button("Hapus aman yang terpilih", disabled=not selected or not confirm, type="secondary"):
        successes, blocked = 0, []
        for aid in selected:
            try:
                store.delete_asset(aid, True)
                successes += 1
                st.session_state.pop("asset_"+aid, None)
            except Exception as e:
                blocked.append(str(e))
        st.success(f"{successes} aset dihapus.")
        if blocked:
            st.warning("\n".join(blocked))
        st.rerun()
    with st.expander("Unduhan file besar via server lokal/VPS"):
        st.caption("Masuk ke uploader port 8502 dengan token yang sama, lalu gunakan ID aset. Endpoint memeriksa token dan membatasi path ke Library.")
        aid = st.text_input("ID aset", key="large_download_id")
        if st.button("Buat tautan unduh 10 menit", key="large_download_token") and aid:
            try:
                from .downloads import download_url
                url = download_url(aid)
                if url:
                    st.link_button("Unduh dari server penyimpanan", url)
                else:
                    st.info("Atur UPLOAD_PUBLIC_URL ke origin HTTPS uploader-port-8502 Anda.")
            except Exception as e:
                st.error(str(e))