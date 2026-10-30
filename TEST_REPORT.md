# Laporan verifikasi — liveoprek2 1.0.0

Tanggal pemeriksaan: **30 Oktober 2026** (Asia/Bangkok).

## Lingkungan aktual

- Linux x86_64, Python 3.13.16.
- FFmpeg/ffprobe 7.1.5 (Debian), libx264, AAC, libass.
- Streamlit 1.66.1, cryptography 50.0.2, Pillow 12.3.0, NumPy 2.3.5.
- yt-dlp 2026.10.26, yt-dlp-ejs 0.8.0, Deno 2.9.8.
- edge-tts 7.3.1, CairoSVG 2.9.1, pytest 9.0.3.

## Hasil yang dijalankan

| Pemeriksaan | Hasil |
|---|---|
| `python -m pytest -q` | **25 passed**, 41.48 detik pada run final |
| Compile seluruh source aplikasi, uploader, launcher, worker, script, relay dan tests | **Lulus** |
| `python scripts/smoke_test.py` | **Lulus**, MP4 H.264 360×640 + AAC, durasi 5.0 detik |
| `python -m pip check` | **No broken requirements found** |
| Ekstrak ZIP lalu `py_compile` ulang | **Lulus untuk 36 berkas Python** |
| Pemeriksaan integritas arsip ZIP | **Lulus**, 64 berkas; tanpa secrets/data uji/cache |
| Live preview Studio port 8501 dan uploader port 8502 | **HTTP 200**, health check keduanya lulus |
| Pemeriksaan sintaks JavaScript uploader dengan Deno | **Lulus** |
| Render nyata keempat partikel | **Lulus**: rain, petals, snow, embers |
| Tipografi, pita, tanda tangan italic, hati SVG | **Lulus** dalam render nyata |
| Normalisasi AAC dua-pass | **Lulus**, 48 kHz stereo; hasil ukur dekat −16 LUFS |
| Reaction nyata dengan audio asli + narasi + banner + ASS | **Lulus** |
| Job poem dan reaction end-to-end dengan fixture lokal | **Lulus** |
| Analisis PCM dan pembuatan spektrogram PNG | **Lulus** |
| Cancel proses FFmpeg | **Lulus** |
| Lock aset terhadap job/live dan penghapusan aman | **Lulus** |
| Enam konfigurasi slot independen | **Lulus**; bukan uji enam channel YouTube produksi |
| Siaran RTMP loopback nyata, tiga FIFO, video berulang dan musik terpisah | **Lulus**, receiver menerima stream video+audio |
| Uploader HTTP 8502: auth, sesi, offset, konflik offset, resume, finalisasi, unduhan HMAC | **Lulus** |
| Google resumable chunk 8 MiB + chunk terakhir | **Lulus dengan transport HTTP simulasi**; urutan Content-Range dan deduplikasi video ID diperiksa |
| OAuth PKCE, state one-time dan ikatan sesi browser | **Lulus dengan unit test**, bukan login Google produksi |
| Streamlit AppTest seluruh tujuh tab, tiga mode Shorts, jalur impor, login password | **Lulus**, tidak ada exception |
| Edge TTS Bahasa Indonesia melalui jaringan | **Lulus**, satu kalimat menghasilkan MP3 sekitar 5 detik |
| Fallback TTS ketika jaringan disimulasikan gagal | **Lulus**, menghasilkan WAV melalui espeak-ng |
| Deno | **Lulus**, versi 2.9.8; installer memakai checksum rilis resmi |
| yt-dlp + Deno pada URL referensi pengguna | **Lulus pengambilan metadata**, ID `tCDG43O80HA`, durasi 22 detik. Bukan bukti semua situs/unduhan akan berhasil |

## Yang TIDAK diklaim sudah diuji

- Tidak ada API key Clipdrop/Ollama atau OAuth client/refresh token produksi dari pengguna. Maka generasi gambar berbayar, respons model gemma4:31b, riset Cloud aktual, pertukaran token Google, upload channel nyata, dan transition live YouTube **belum diuji terhadap akun produksi**. Adapter dan kegagalan/simulasi protokol diuji terpisah.
- Tidak melakukan publikasi video atau siaran ke akun pengguna selama pengujian.
- Tidak menguji ketahanan 24 jam, beban enam encoder parallel, atau kapasitas Streamlit Cloud. Batas slot bukan jaminan sumber daya.
- Dockerfile/Compose dan contoh systemd disediakan tetapi Docker daemon/systemd tidak tersedia dalam sandbox verifikasi; tidak diklaim sudah dijalankan di sini.
- Build/deploy ke akun Streamlit Cloud pengguna tidak dilakukan. Dependency dan entrypoint diperiksa secara lokal.
- Tidak ada jaminan viral, CTR, monetisasi, ketersediaan layanan TTS pihak ketiga, atau hasil pengenalan lagu dari spektrogram.
- Tidak ada klaim secure erase RAM permanen untuk key Clipdrop; yang diuji/diterapkan adalah tidak dipersistensikan dan pembersihan referensi best-effort.

## Catatan desain pengujian

Fixture media dibuat sintetis oleh FFmpeg/Pillow, bukan media berhak cipta. Uji Google/OAuth memakai respons palsu agar tidak mengubah akun nyata. Uji RTMP memakai receiver lokal. Data uji terisolasi dari data aplikasi dan tidak dimasukkan ke ZIP. Hasil TTS jaringan hanya memeriksa keberhasilan sintesis dan durasi, bukan penilaian mutu audio formal.

Periksa kembali integrasi eksternal setelah mengisi kredensial Anda. Mulai dengan unggahan **private**, satu slot live, dan resolusi 720p sebelum meningkatkan beban.