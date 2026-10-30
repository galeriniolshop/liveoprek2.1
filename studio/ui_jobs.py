from __future__ import annotations
from pathlib import Path
import shutil
import time
import streamlit as st
from . import store, worker
from .config import DATA, LOGS, WORK
from .ui_common import human


def render():
    st.subheader("Antrean & kesehatan penyimpanan")
    w = worker.ensure_worker()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Worker", "Aktif" if w["running"] else "Nonaktif")
    jobs = store.rows("SELECT * FROM jobs ORDER BY created DESC LIMIT 200")
    c2.metric("Menunggu", sum(j["status"] == "queued" for j in jobs))
    c3.metric("Diproses", sum(j["status"] == "running" for j in jobs))
    usage = shutil.disk_usage(DATA)
    c4.metric("Disk bebas", human(usage.free))
    st.progress(min(1.0, usage.used/max(1,usage.total)), text=f"Disk terpakai {human(usage.used)} / {human(usage.total)}")
    assets = store.assets()
    st.caption(f"Library: {len(assets)} aset · {human(sum(a['bytes'] for a in assets))}. Worker render berjalan serial; slot live memiliki proses independen.")
    if usage.free < 2*1024**3:
        st.warning("Disk bebas <2 GiB. Hentikan impor besar dan bersihkan aset yang tidak digunakan.")
    if not w["running"]:
        st.info("AUTO_START_WORKER=false. Jalankan python -m studio.worker pada server yang sama.")
    status = st.selectbox("Filter status", ["all","queued","running","done","error","cancelled"], format_func=lambda x: "Semua" if x == "all" else x)
    shown = [j for j in jobs if status == "all" or j["status"] == status]
    for j in shown[:60]:
        with st.expander(f"{j['status'].upper()} · {j['label']} · {int(j['progress']*100)}%", expanded=j["status"] == "running"):
            st.caption(f"ID {j['id']} · percobaan {j['attempts']} · diperbarui {time.strftime('%H:%M:%S',time.localtime(j['updated']))}")
            st.progress(j["progress"], text=j["stage"])
            if j["error"]:
                st.error(j["error"])
            result = __import__("json").loads(j["result"])
            if result.get("asset_id"):
                try:
                    a = store.asset(result["asset_id"])
                    st.success("Hasil: "+a["name"])
                    p = store.asset_path(a)
                    if a["kind"] == "video" and a["bytes"] < 150*1024**2:
                        st.video(p)
                    elif a["kind"] == "audio" and a["bytes"] < 60*1024**2:
                        st.audio(p)
                    elif a["kind"] == "image":
                        st.image(p)
                    if a["bytes"] < 200*1024**2:
                        with open(p,"rb") as f:
                            st.download_button("Unduh hasil", f, file_name=a["name"], key="resultdl"+j["id"])
                except Exception as e:
                    st.warning(str(e))
            if result.get("url"):
                st.link_button("Buka video YouTube", result["url"])
                st.caption(result.get("note", ""))
            if result.get("upload_job_id"):
                st.caption("Auto-upload job: "+result["upload_job_id"])
            if result.get("srt") and Path(result["srt"]).exists():
                with open(result["srt"],"rb") as f:
                    st.download_button("Unduh subtitle .srt", f, file_name="reaction.srt", key="srt"+j["id"])
            c1, c2 = st.columns(2)
            if j["status"] in ("queued","running"):
                if c1.button("Batalkan", key="cancel"+j["id"]):
                    if j["status"] == "queued":
                        store.update_job(j["id"], status="cancelled", stage="Dibatalkan")
                        store.unlock("job:"+j["id"])
                    else:
                        store.update_job(j["id"], stage="Membatalkan…")
            if j["status"] in ("error","cancelled"):
                if c2.button("Retry job", key="retry"+j["id"]):
                    try:
                        payload = __import__("json").loads(j["payload"])
                        inputs = payload.get("music_ids", [])[:]
                        for k in ("asset_id","source_id","image_id"):
                            if payload.get(k):
                                inputs.append(payload[k])
                        store.lock_assets(inputs, "job:"+j["id"], replace=True)
                        store.update_job(j["id"], status="queued", stage="Menunggu retry", error="", progress=0)
                    except Exception as e:
                        st.error(str(e))
            if st.checkbox("Tampilkan log", key="showlog"+j["id"]):
                st.code(store.log_tail(j["id"]), language="text")
    with st.expander("Pemeliharaan & log worker"):
        st.caption("Pembersihan hanya menyasar temporary job yang sudah tidak aktif dan log lama. Library, sesi upload, analisis, serta slot live tidak dihapus otomatis.")
        confirm = st.checkbox("Konfirmasi bersihkan temporary job selesai dan log >7 hari")
        if st.button("Bersihkan temporary & log lama", disabled=not confirm):
            active = {j["id"] for j in store.rows("SELECT id FROM jobs WHERE status IN ('queued','running')")}
            removed = 0
            for p in WORK.iterdir():
                if p.is_dir() and p.name not in active and len(p.name) == 32:
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
            for p in LOGS.glob("*.log"):
                if p.stat().st_mtime < time.time()-7*86400:
                    p.unlink(missing_ok=True)
            st.success(f"{removed} folder temporary dibersihkan.")
        p = LOGS/"worker.log"
        st.code(p.read_text(errors="replace")[-12000:] if p.exists() else "Belum ada log worker.", language="text")