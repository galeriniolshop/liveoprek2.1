# Studio Render & Live — liveoprek2

Aplikasi Streamlit satu folder untuk mengelola Library, membuat Shorts, mengimpor media, menormalisasi audio/video, dan menjalankan hingga enam siaran independen. UI berbahasa Indonesia.

**Baca dahulu:** paket ini siap dijalankan dan siap diproses build Streamlit Cloud, tetapi Cloud **bukan host live 24/7** dan **tidak membuka port 8502 untuk publik**. Semua fitur ada dalam kode; operasi berkelanjutan dan impor resumable besar memerlukan komputer/VPS yang selalu aktif. Tidak ada akun Google, channel, API key, atau konten berlisensi yang dibundel.

## 1. Mulai cepat di komputer/VPS

Prasyarat: Linux, Python **3.13**, FFmpeg/ffprobe dengan libx264, libass, AAC; paket sistem pada `packages.txt`. Windows disarankan memakai WSL2. macOS dapat memakai Homebrew untuk ffmpeg/espeak-ng/cairo dan installer Deno resmi.

```bash
unzip liveoprek2.zip
cd liveoprek2
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Debian/Ubuntu; jalankan sebagai administrator bila diperlukan:
sudo apt-get install ffmpeg espeak-ng libcairo2 fonts-dejavu-core
python scripts/install_deno.py
python run_local.py
```

- Studio: `http://localhost:8501`
- Uploader resumable: `http://localhost:8502`
- Worker otomatis dijalankan oleh `run_local.py`.
- `Ctrl+C` menghentikan studio, uploader, dan worker yang diluncurkan launcher.
- Data default: `data/` di folder aplikasi; janganhapus folder ini saat upgrade.

Untuk development tanpa launcher:

```bash
streamlit run app.py
# Terminal lain, DATA yang sama:
python -m studio.worker
python upload_server.py --port 8502
```

Jangan menjalankan dua deployment berbeda pada satu folder data. SQLite menggunakan WAL dan lock, tetapi rancangan operasionalnya satu studio per volume data.

### Docker Compose (disarankan untuk VPS)

```bash
cp .env.example .env
# Edit .env: APP_PASSWORD dan APP_SECRET wajib diganti.
docker compose up -d --build
```

Tiga container berbagi volume `/data`: studio, worker, uploader. Port host di-bind ke loopback; pasang HTTPS reverse proxy sebelum akses publik. Contoh Caddy ada di `deploy/Caddyfile.example`.

Alternatif systemd: tiga contoh unit di `deploy/`. Sesuaikan user, path virtualenv, `/var/lib/liveoprek2`, dan `/etc/liveoprek2/env`. **Restart studio juga menghentikan supervisor live anaknya**; hentikan siaran dari UI sebelum maintenance. Worker dan uploader mempunyai unit terpisah.

## 2. Deploy Streamlit Cloud

1. Ekstrak ZIP, lalu unggah **isi folder `liveoprek2/`** ke repository GitHub Anda. `app.py`, `requirements.txt`, dan `packages.txt` harus sejajar. Jangan commit data, `.env`, atau secrets.
2. Buat app di Streamlit Community Cloud, entrypoint `app.py`, Python **3.13**.
3. Salin isi `.streamlit/secrets.example.toml` ke kolom **Secrets**, bukan menamai file contoh sebagai secrets aktif.
4. Isi minimal `APP_PASSWORD`, `APP_SECRET` acak panjang, `DEPLOYMENT_MODE="cloud"`, dan `LIVEOPREK_DATA="/tmp/liveoprek2-data"`.
5. Isi kunci layanan yang akan dipakai. Deploy. Buka tab **Normalisasi & Tes**, lalu **Job & Disk**.
6. Deno tidak tersedia sebagai paket apt Debian standar. Tab **Impor → Unduh URL → Siapkan Deno** menjalankan installer rilis resmi dengan verifikasi SHA256 ke folder data. Keberhasilan eksekusi binary bergantung pada kebijakan filesystem host; bila ditolak, gunakan VPS. Jangan memasukkan package Python palsu bernama `deno` atau `ffmpeg`.

### Batas Cloud yang tidak bisa dijanjikan oleh kode

- Filesystem lokal bersifat sementara: reboot/redeploy dapat menghapus Library, SQLite, token, dan binary Deno. `APP_SECRET` tetap harus stabil agar backup data/token dapat didekripsi lagi. Untuk produksi, backup volume data dan gunakan penyimpanan eksternal yang dimount pada VPS.
- Worker/supervisor adalah subprocess, bukan layanan terkelola dengan SLA. App sleep, OOM, atau restart dapat menghentikannya. Job running yang terinterupsi ditandai error saat worker kembali; tekan Retry setelah memeriksa penyebab. Upload YouTube memakai sesi tersimpan, bukan otomatis mengunggah ulang tanpa keputusan operator.
- Port 8502 tidak menjadi URL publik tambahan pada satu app Cloud. Gunakan **Upload browser biasa** di Cloud, atau jalankan uploader pada VPS dengan volume/data yang sesuai. Jangan mengira `UPLOAD_PUBLIC_URL` membuat Cloud mengekspos port baru.
- Render 1080p, apalagi enam live sekaligus, dapat melebihi CPU/RAM/bandwidth Cloud. Mulai dari 720p dan satu slot. Enam slot adalah batas arsitektur, **bukan jaminan kapasitas hosting**.
- Untuk live sungguhan 24 jam, gunakan VPS/server selalu aktif, monitoring, bandwidth cukup, dan uji stabilitas terlebih dahulu.

## 3. Secrets dan keamanan

| Kunci | Fungsi |
|---|---|
| `APP_PASSWORD` | Password admin UI. Wajib untuk penggunaan API di deployment publik. |
| `APP_SECRET` | Secret acak >=32 karakter untuk enkripsi token OAuth, RTMP, dan URI upload. Jangan ganti tanpa rencana migrasi. |
| `OLLAMA_API_KEY` | Kunci Ollama Cloud, disimpan di server, bukan URL. |
| `OLLAMA_MODEL` | Default `gemma4:31b` (nama API; alias CLI `gemma4:31b-cloud`). |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client **Web application**, bukan menaruh refresh token manual di browser. |
| `GOOGLE_REDIRECT_URI` | Default `https://redirect1x.streamlit.app`; harus sama persis dengan URI terdaftar. |
| `YOUTUBE_API_KEY` | Opsional untuk pencarian resmi YouTube Data API; memakai kuota. Tanpa ini riset memakai Ollama web_search dan/atau OAuth. |
| `UPLOAD_PUBLIC_URL` | Origin HTTPS uploader 8502, misalnya `https://upload.example.com`. Bukan URL localhost untuk pengunjung remote. |
| `UPLOAD_TOKEN` | Token uploader >=24 karakter. Bila kosong, dibuat di `data/upload.token`, mode 0600. |
| `LIVEOPREK_DATA` | Folder data persisten; environment variable lebih diutamakan daripada secrets. |
| `AUTO_START_WORKER` | Default true; false pada Compose/systemd dengan worker terpisah. |
| `MAX_LIVE_SLOTS` | 1–6; batas administratif tambahan. |
| `MAX_ASSET_BYTES` | Batas ukuran aset; default 8 GiB, melalui environment variable. |
| `IMPORT_ALLOWED_HOSTS` | Allowlist host unduhan; default YouTube, SoundCloud, Vimeo. |
| `IMPORT_REMOTE_COMPONENTS` | true: solver EJS dari npm; false: GitHub. Keduanya perlu jaringan. |
| `ALLOW_PUBLIC_ACCESS` |Jangan aktifkan pada produksi. Izin tanpa password hanya untuk uji lokal terisolasi. |

Aplikasi ini **single-admin/shared-team**, bukan multi-tenant. Semua orang yang mengetahui password dapat mengakses Library dan channel terhubung. Gunakan HTTPS, akses privat, dan password panjang. Jangan bagikan tangkapan layar panel token/RTMP. Streamlit query string dapat direkam proxy/riwayat meskipun aplikasi menghapusnya.

Token OAuth/config RTMP/session URI dienkripsi dengan Fernet yang diturunkan dari `APP_SECRET`. Tanpa secret eksplisit, aplikasi membuat `data/master.key` untuk kemudahan lokal; kehilangan key berarti token tidak dapat dipulihkan. Library media tidak dienkripsi. Backup harus mencakup SQLite dan key/secret yang sama, dengan akses ketat.

## 4. OAuth multi-channel dan relay

1. Aktifkan **YouTube Data API v3** pada Google Cloud project.
2. Konfigurasi OAuth consent screen dan tambahkan akun operator sebagai test user bila aplikasi masih testing.
3. Buat OAuth client **Web application**. Daftarkan redirect URI `https://redirect1x.streamlit.app` (atau domain milik Anda).
4. Isi client ID/secret di Secrets studio.
5. Di tab Viral Shorts/Live, buka panel OAuth → **Hubungkan / tambah channel** → buka izin Google.
6. Relay menampilkan URL callback berisi `code` dan `state`. **Salin URL lengkap** dan tempel pada sesi Studio yang memulai koneksi. Aplikasi mengikat state ke sesi browser, memakai PKCE S256, expiry 10 menit, dan one-time state.
7. Channel yang dikembalikan `channels.list(mine=true)` disimpan. Ulangi untuk akun/brand channel lain. Pilih channel secara terpisah pada upload/live.

**Domain `redirect1x.streamlit.app bukan infrastruktur yang otomatis dibuat/dikuasai paket ini.** Saat制作 paket, URL tersebut menampilkan halaman app tidur; tidak ada deployment ke akun Anda yang dilakukan. Folder `relay/` adalah aplikasi relay terpisah yang bisa Anda deploy pada hostname redirect yang Anda kendalikan. Jika tidak menguasai nama `redirect1x`, Anda tidak dapat mendaftarkan app baru pada subdomain orang lain: buat hostname sendiri dan ubah `GOOGLE_REDIRECT_URI` serta allowlist Google. Relay tidak meminta client secret dan tidak menukar token.

Jangan menyelesaikan callback pada sesi baru bila state dibuat di sesi lama; itu akan ditolak. Tombol Buka Studio boleh dipakai untuk navigasi, tetapi tempel callback ke sesi asal. Putuskan channel mencabut refresh token dan menghapus catatan lokal; hentikan slot yang memakai channel terlebih dahulu.

Scopes: `youtube.upload`, `youtube.force-ssl`, `youtube.readonly`. Izin ini sensitif; hubungkan hanya channel yang Anda kelola.

## 5. Fitur dan cara pakai

### Library

Cari nama, filter video/audio/gambar, pilih semua pada halaman atau kosongkan, preview, unduh, dan hapus dengan konfirmasi. Aset yang direferensikan job queued/running atau playlist slot live dikunci secara transaksional. Untuk menghapus, batalkan job atau ubah/kosongkan playlist lalu lepas kunci slot. Slot yang sudah disimpan tetap mengunci aset walaupun sedang stopped, agar start berikutnya tidak kehilangan media.

Preview/download inline dibatasi agar tidak memuat video besar ke RAM. File >200 MiB dapat diunduh melalui endpoint uploader bertanda tangan HMAC berlaku 10 menit; perlu `UPLOAD_PUBLIC_URL` dan uploader yang berbagi data dengan studio.

### Impor

- **Resumable 8502:** UI mandiri dengan fetch URL relatif ke origin sendiri. Chunk browser 1 MiB; server menerima sampai 8 MiB. ID sesi disimpan di sessionStorage, GET mengembalikan offset/name/size, PATCH menolak offset salah. Klik Jeda lalu Mulai untuk lanjut. Untuk pindah browser, salin ID sesi, masukkan ke `sessionStorage.uploadSid` pada origin uploader, isi token, pilih file identik. Jangan gunakan file berbeda pada sesi yang sama.
- Partial chunk yang terputus ditulis ulang dari offset terkonfirmasi. Finalisasi dapat diulang. File diverifikasi ffprobe/Pillow dan disalin atomik ke Library; source tidak ditimpa. Deduplikasi memakai SHA256 + ukuran. Butuh ruang disk untuk salinan sumber dan Library saat finalisasi.
- **Browser biasa:** beberapa file sekaligus, dibatasi `server.maxUploadSize=200` MiB.
- **URL:** job yt-dlp dengan Deno dan yt-dlp-ejs; video maksimum 720p agar hemat, atau ekstrak audio AAC M4A. Tidak ada playlist massal, shell user, cookies login, atau bypass DRM. Hanya unduh konten yang Anda miliki/berizin. Kegagalan situs/ekstraktor dilaporkan apa adanya.

### Clipdrop → Video

Form browser menempatkan key dalam query sementara dan memuat ulang app agar request dapat diproses. Server segera menghapus parameter, memakai key untuk satu POST `https://clipdrop-api.co/text-to-image/v1`, menutup response, menghapus referensi lokal dan menjalankan GC. Key **tidak** masuk SQLite, session_state, file, log, atau job. Bila login ulang diperlukan setelah reload, selesaikan login dahulu; jangan bagikan URL saat parameter masih tampak.

**Batas teknis:** request yang diproses Python tidak mungkin secara harfiah hanya hidup di browser. Python immutable strings, allocator, browser, dan proxy tidak menyediakan jaminan secure forensic erase. Yang diterapkan adalah minimisasi retensi dan pembersihan best-effort, bukan klaim RAM mustahil bocor. Gunakan studio privat; cabut key bila pernah terekspos. Kredit/kuota Clipdrop mengikuti akun Anda.

Gambar masuk Library, lalu job FFmpeg membuat zoompan halus, partikel hujan/kelopak/salju/bara, dan musik pilihan menjadi MP4 H.264/AAC. API gambar tidak menerima rasio khusus di integrasi ini: prompt meminta komposisi vertikal, lalu renderer melakukan crop 9:16. Hasil background mungkin perlu diperiksa komposisinya.

### Viral Shorts A — kartu kata

Ollama mengambil referensi melalui web_search nyata dan, bila tersedia, YouTube Data API (30 hari, urut views). Hasil diberi URL/sumber; angka views tidak dikarang. Model menyusun bait orisinal, ribbon kapital, metadata, dan prompt visual. Anda dapat mengedit sebelum render.

Renderer membuat pita atas, bait rata tengah, tanda tangan italic kanan bawah, dan hati dari path SVG vektor yang dirasterisasi untuk komposit MP4. Partikel adalah loop alpha asli. Musik dipilih acak dari pool Library; pool kosong menghasilkan audio hening. Output 720×1280 atau 1080×1920, 30 fps, 5–60 detik. Riset/model tidak menjamin viral atau CTR.

### Viral Shorts B — reaction

Pilih klip Library (impor referensi YouTube yang Andaizinkan atau upload sendiri). Berikan konteks; AI boleh memakai tiga sampel frame, bukan mengklaim menonton seluruh video. Naskah gaya Warga +62 dapat diedit. TTS default `id-ID-GadisNeural` atau `id-ID-ArdiNeural` melalui edge-tts, memerlukan internet dan dapat berubah. Fallback eksplisit espeak-ng tersedia, tetapi kualitasnya robot, bukan neural.

Setiap kalimat disintesis terpisah. Durasi audio aktual menentukan subtitle; jeda dan atempo mempertahankan kalimat utuh. Bila tetap terlalu panjang, job gagal dengan pesan memperpendek naskah, bukan diam-diam memotong ucapan. Subtitle yang dihasilkan adalah **teks reaksi TTS otomatis**, bukan transkripsi ucapan asli klip. Audio asli di-duck dengan sidechaincompress terhadap TTS, dicampur, dinormalisasi, dan diberi banner atas. Output MP4 9:16; SRT tersedia pada Job selesai. Klip tanpa audio tetap mendapat track asli hening sehingga graph ducking stabil.

### Upload Shorts

Panel manual atau auto-upload setelah render. Ollama dapat menyusun judul/deskripsi/hashtag/tags; semua tetap dapat diedit. Auto-upload memerlukan pilihan channel dan persetujuan hak konten secara eksplisit. Default **private**. Publik adalah keputusan operator. Media realistis sintetis diberi disclosure default; setelan anak harus diperiksa.

Implementasi Google Resumable Upload: inisiasi mendapatkan Location, PUT tepat **8 MiB** kecuali chunk terakhir, Content-Range benar, status 308 dibaca offsetnya, respons 200/201 menghasilkan video ID. URI sesi dan offset disimpan terenkripsi. Retry manual melanjutkan sesi; sesi kedaluwarsa diinisiasi ulang. Batas operasi upload enam jam per percobaan job. Video ID yang sudah selesai dipakai ulang untuk metadata/file/channel yang sama agar tidak duplikat.

YouTube dapat memaksa hasil unggahan proyek API yang belum diaudit menjadi private. Kuota, kelayakan channel, pemrosesan, copyright, dan kebijakan platform berada di luar kendali aplikasi. Tidak ada jaminan lolos monetisasi atau rekomendasi algoritma.

### Normalisasi & Tes

Audio: dua-pass EBU R128 → AAC M4A, 48 kHz stereo, target default −16 LUFS, true peak ≤−1.5 dBTP. Video: H.264/AAC MP4, fit tanpa crop, 1280×720 atau 720×1280. Sumber tidak diubah. Panel tes memeriksa binary, Deno, key, dan izin tulis tanpa memanggil API berbayar.

### Live 24 jam

Enam slot dengan konfigurasi, proses, log, start/stop, heartbeat, dan reconnect terpisah. Setiap slot mempunyai:

1. Pipe rawvideo: opening opsional **sekali per start**, lalu deck video acak berulang.
2. Pipe PCM musik: track dipilih acak dan didekode utuh; perpindahan video tidak mereset musik.
3. Pipe PCM audio asli: mengikuti klip; bila klip tidak mempunyai audio atau audio asli dimatikan, menghasilkan hening berdurasi sama.

Ketiganya masuk satu FFmpeg, audio dicampur tanpa normalisasi amix yang mengecilkan sinyal otomatis, lalu limiter. Output H.264/AAC through tee FLV ke YouTube OAuth dan/atau maksimal empat tujuan total per slot. RTMP keys disimpan terenkripsi dan log disanitasi. Kegagalan satu tujuan tee di-ignore agar tujuan lain tetap hidup; periksa log karena platform tertentu bisa tetap gagal. Reconnect pendek dibatasi delapan kali sebelum berhenti, bukan spam tanpa batas.

YouTube: membuat liveStream + broadcast, bind, menunggu ingest aktif, transition testing lalu live. Stop normal meminta transition complete. Force-stop dapat meninggalkan broadcast yang perlu diselesaikan dari YouTube Studio. Setelah app/server reboot, slot tidak otomatis publish ulang; periksa dan Start manual.

Auto-metadata memakai ffprobe, sampel PCM, RMS/ZCR/centroid/rolloff/flux, estimasi tempo autocorrelation, dan spektrogram yang benar-benar dihitung. Gambar spektrogram dikirim bersama fitur numerik ke model vision Ollama, ditambah riset web. Ini **heuristik konten audio**, bukan pengenalan lagu/artis/suara atau transkripsi. Jangan menganggap hasil spektral membuktikan identitas artis. Metadata manual yang sudah disimpan lebih diutamakan.

Perkiraan upload: `slot × (video kbps + 128) × tujuan × 1.2 / 1000` Mbps. Enam slot 2500 kbps ke dua tujuan ≈37.8 Mbps sebelum overhead. CPU bergantung pada preset/resolusi/fps; lakukan load test. Untuk awal: 720p/24 fps, 2500 kbps, satu slot. Musik yang berganti tetap utuh, tetapi transisi antartrack tidak dirancang sebagai DJ crossfade sampel-akurat.

### Job & Disk

Antrean SQLite persisten, worker render serial untuk membatasi beban, progres/log/error per job, cancel kooperatif, retry manual, hasil preview/download, tautan YouTube, SRT, status disk, dan pembersihan temporary job tidak aktif. Live berjalan paralel di luar antrean render. Upload yang sedang berjalan mungkin memerlukan waktu hingga timeout HTTP sebelum pembatalan diproses.

## 6. Uji

```bash
pip install -r requirements-dev.txt
python -m compileall -q app.py upload_server.py run_local.py studio scripts tests relay/app.py
python -m pytest -q
python scripts/smoke_test.py
```

Tes mencakup media sintetis asli, semua partikel, loudness, graph ducking, pembatalan FFmpeg, penguncian aset, HTTP resumable nyata, chunk Google 8 MiB dengan respons HTTP simulasi, PKCE/session binding, UI seluruh tab/mode, dan siaran RTMP loopback nyata. Tidak ada kredensial produksi dalam pengujian. Lihat `TEST_REPORT.md` untuk hasil dan batas pengujian eksternal.

## 7. Troubleshooting

- **Worker nonaktif:** jalankan `python -m studio.worker`, periksa `data/logs/worker.log`, dan pastikan satu folder data. Job lama setelah OOM perlu Retry manual.
- **Deno tidak ditemukan:** jalankan installer, atau pasang binary resmi ke PATH. Pastikan akses npm/GitHub untuk EJS; jangan menghapus dependensi yt-dlp-ejs.
- **Clipdrop 401/402/429:** cek key, kredit, dan kuota; request berikutnya perlu key baru karena aplikasi sengaja tidak menyimpannya.
- **OAuth redirect mismatch:** cocokkan string URI persis, tipe client Web, dan kepemilikan hostname. Callback harus kembali ke sesi asal.
- **OAuth no refresh token:** cabut izin app pada akun Google lalu consent ulang. Akun harus memiliki channel yang dapat dikelola.
- **YouTube upload private terus:** periksa audit/kebijakan proyek API dan pembatasan channel, bukan hanya tombol public.
- **Live tidak aktif:** cek stream key, kuota live, fitur live akun, resolusi/fps, log FFmpeg, serta bandwidth. Akun baru dapat memerlukan aktivulasi fitur live.
- **TTS gagal:** layanan Edge bukan API berSLA; coba lagi atau pilih fallback lokal secara sadar.
- **File hilang setelah Cloud reboot:** itu batas filesystem ephemeral; pulihkan backup atau pindah ke VPS/volume persisten.
- **APP_SECRET diganti:** token/config lama tidak bisa didekripsi. Pulihkan secret lama; jangan menghapus data sembarangan.

## Referensi resmi

- Ollama Cloud: https://docs.ollama.com/cloud
- Model: https://ollama.com/library/gemma4:31b-cloud
- Ollama web search: https://docs.ollama.com/capabilities/web-search
- Clipdrop API: https://clipdrop.co/apis/docs/text-to-image
- Google resumable: https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- YouTube live: https://developers.google.com/youtube/v3/live/docs/liveBroadcasts
- YouTube synthetic disclosure: https://developers.google.com/youtube/v3/docs/videos
- yt-dlp EJS: https://github.com/yt-dlp/yt-dlp/wiki/EJS
- Streamlit dependencies: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies

Lisensi kode: MIT. Font DejaVu: lihat `assets/fonts/LICENSE.txt`. Hak media dan ketentuan layanan pihak ketiga tidak diberikan oleh lisensi aplikasi.