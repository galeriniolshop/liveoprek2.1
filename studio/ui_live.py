from __future__ import annotations
import json
from pathlib import Path
import time
import streamlit as st
from . import store, live, ai, media, youtube
from .security import encrypt
from .config import secret, ANALYSIS
from .ui_common import channel_manager, channel_select, metadata_panel, choose


def slot_panel(slot):
    row = live.state(slot)
    status = row["status"]
    active = status in live.ACTIVE
    labels = {"stopped":"Berhenti", "starting":"Menyiapkan", "running":"Mengudara", "reconnecting":"Reconnect", "stopping":"Menghentikan", "error":"Error"}
    with st.container(border=True):
        st.markdown(f"### Slot {slot} · {row['name']} · {labels.get(status, status)}")
        st.caption(f"PID {row.get('pid') or '—'} · heartbeat {time.strftime('%H:%M:%S', time.localtime(row['heartbeat'])) if row.get('heartbeat') else '—'}")
        if row.get("error"):
            st.warning(row["error"])
        c1, c2, c3 = st.columns(3)
        if c1.button("Start siaran", key=f"start{slot}", disabled=active, type="primary"):
            try:
                live.start(slot)
                st.rerun(scope="fragment")
            except Exception as e:
                st.error(str(e))
        if c2.button("Stop / complete", key=f"stop{slot}", disabled=not active):
            live.stop(slot)
            st.rerun(scope="fragment")
        if c3.button("Paksa stop", key=f"kill{slot}", disabled=not active):
            live.stop(slot, force=True)
            st.rerun(scope="fragment")
        cfg = live.config(slot)
        with st.form(f"config{slot}"):
            name = st.text_input("Nama slot", row["name"], key=f"name{slot}")
            videos = store.assets("video")
            audio = store.assets("audio")
            vids = choose("Playlist video acak berulang", videos, f"videos{slot}", cfg.get("videos", []))
            lookup = {a["id"]: a for a in videos}
            opening = st.selectbox("Opening (sekali per start)", [""]+list(lookup),
                                   index=([""]+list(lookup)).index(cfg.get("opening") or ""),
                                   format_func=lambda x: lookup[x]["name"] if x else "Tanpa opening", key=f"opening{slot}")
            aids = choose("Pool musik random kontinu · lagu utuh", audio, f"audio{slot}", cfg.get("audio", []))
            st.caption("Tanpa musik: pipe musik hening. Video tanpa audio: pipe audio asli menghasilkan hening berdurasi sama. Pergantian video tidak mereset lagu.")
            c1, c2, c3 = st.columns(3)
            vertical = c1.checkbox("Vertikal 9:16", value=cfg.get("vertical", False), key=f"vertical{slot}")
            fps = c2.selectbox("FPS", [24, 25, 30], index=[24,25,30].index(cfg.get("fps",24)), key=f"fps{slot}")
            bitrate = c3.number_input("Video kbps", 800, 8000, int(cfg.get("bitrate",2500)), 100, key=f"bitrate{slot}")
            c1, c2, c3 = st.columns(3)
            original = c1.checkbox("Sertakan audio asli", value=cfg.get("original_audio", True), key=f"original{slot}")
            mv = c2.slider("Volume musik", 0.0, 1.5, float(cfg.get("music_volume", .35)), .05, key=f"mv{slot}")
            ov = c3.slider("Volume asli", 0.0, 1.5, float(cfg.get("original_volume", .8)), .05, key=f"ov{slot}")
            account = st.selectbox("Channel YouTube (opsional bila RTMPmanual)", [""]+ [a["id"] for a in youtube.accounts()],
                                   index=([""]+[a["id"] for a in youtube.accounts()]).index(cfg.get("account_id") or ""),
                                   format_func=lambda x: next((a["title"] for a in youtube.accounts() if a["id"] == x), "Tidak pakai YouTube OAuth"), key=f"account{slot}")
            rtmp = st.text_area("Manual RTMP / RTMPS · satu URL lengkap per baris", cfg.get("manual_rtmp", ""), height=90,
                                key=f"rtmp{slot}", help="Server dan stream key dalam satu URL. Disimpan terenkripsi; tidak dicetak pada log.")
            privacy = st.selectbox("Privasi siaran YouTube", ["private", "unlisted", "public"],
                                   index=["private","unlisted","public"].index(cfg.get("privacy","private")), key=f"privacy{slot}")
            topic = st.text_input("Topik / nama program untuk riset & metadata", cfg.get("topic", "Musik santai teman belajar"), key=f"topic{slot}")
            automatic = st.checkbox("Auto-metadata Ollama saat start bila metadata manual kosong", value=cfg.get("auto_metadata", True), key=f"autometa{slot}")
            saved = st.form_submit_button("Simpan konfigurasi slot", disabled=active)
        if saved:
            try:
                new = {"videos": vids, "audio": aids, "opening": opening or None, "vertical": vertical, "fps": fps,
                       "bitrate": bitrate, "original_audio": original, "music_volume": mv, "original_volume": ov,
                       "account_id": account or None, "manual_rtmp": rtmp, "privacy": privacy, "topic": topic,
                       "auto_metadata": automatic, "name": name}
                # Keep manual metadata only if topic hasn't changed.
                if cfg.get("topic") == topic and cfg.get("metadata"):
                    new["metadata"] = cfg["metadata"]
                live.save_config(slot, new, name)
                st.success("Tersimpan. Aset playlist dikunci dari penghapusan.")
            except Exception as e:
                st.error(str(e))
        with st.expander("Judul, deskripsi & hashtag Live"):
            meta = metadata_panel(f"live{slot}", cfg.get("metadata", {"title": row["name"], "description": cfg.get("topic", "")}), live=True)
            c1, c2 = st.columns(2)
            if c1.button("Simpan metadata manual", key=f"savemeta{slot}", disabled=active):
                cfg["metadata"] = meta
                live.update(slot, vault=encrypt(json.dumps(cfg)))
                st.success("Metadata manual tersimpan.")
            if c2.button("Analisis PCM + riset + racik sekarang", key=f"analyze{slot}", disabled=active):
                try:
                    saved_cfg = live.config(slot)
                    paths = [store.asset_path(a) for a in saved_cfg.get("audio", [])[:3]]
                    if not paths:
                        paths = [store.asset_path(a) for a in saved_cfg.get("videos", [])[:3] if media.has_audio(store.asset_path(a))]
                    with st.spinner("ffprobe → PCM → spektrogram → Ollama…"):
                        evidence = media.analyze_audio(paths, ANALYSIS/f"live-{slot}") if paths else {"tracks": [], "method": "Tidak ada audio"}
                        public = json.loads(json.dumps(evidence))
                        for t in public.get("tracks", []):
                            t.pop("spectrogram", None)
                        research = ai.web_research(topic, "live", account or None)
                        generated = ai.metadata(topic, {"audio_analysis": public, "research": research}, live=True,
                                                images=[t["spectrogram"] for t in evidence.get("tracks", []) if Path(t.get("spectrogram", "")).is_file()])
                    saved_cfg["metadata"] = generated
                    live.update(slot, vault=encrypt(json.dumps(saved_cfg)))
                    store.kv_set(f"live-meta-{slot}", {"metadata": generated, "analysis": evidence, "research": research})
                    st.success("Metadata berbasis sinyal audio + riset tersimpan.")
                    st.rerun(scope="fragment")
                except Exception as e:
                    st.error(str(e))
            analysis = store.kv_get(f"live-meta-{slot}")
            if analysis:
                for track in analysis.get("analysis", {}).get("tracks", []):
                    if Path(track.get("spectrogram", "")).exists():
                        st.image(track["spectrogram"], caption="Spektrogram nyata dari sampel PCM")
                st.caption("Fitur spektral bukan pengenalan lagu/artis. Ollama tidak diberi klaim identitas lagu yang tidak terbukti.")
        with st.expander("Log slot terpisah"):
            st.code(live.log_tail(slot), language="text")
        if st.button("Lepas kunci playlist slot", key=f"unlock{slot}", disabled=active):
            if cfg:
                st.warning("Konfigurasi tetap ada, tetapi aset tidak lagi dikunci. Jangan hapus aset sebelum menggantinya.")
                store.unlock(f"live:{slot}")


def render():
    st.subheader("Live 24 jam · enam slot independen")
    st.warning("Target deployment live: VPS/server selalu aktif. Streamlit Cloud dapat tidur/restart dan tidak menjamin proses 24/7. Enam siaran memerlukan CPU dan upload bandwidth yang memadai.")
    running = sum(live.state(i)["status"] in live.ACTIVE for i in range(1,7))
    c1, c2, c3 = st.columns(3)
    c1.metric("Slot aktif", f"{running} / {min(6, int(secret('MAX_LIVE_SLOTS', '6')))}")
    c2.metric("Arsitektur", "3 pipe / slot")
    c3.metric("Simulcast", "FFmpeg tee")
    st.caption("Estimasi bandwidth: jumlah slot × (video kbps + 128 kbps audio) × jumlah tujuan × 1.2 overhead. Contoh 6 × 2.628 Mbps × 2 tujuan ≈ 37.8 Mbps sebelum overhead.")
    channel_manager("live_oauth")
    for slot in range(1,7):
        slot_panel(slot)