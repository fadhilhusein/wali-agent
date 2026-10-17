# Audit tahap 1: laporan pengujian

Branch `checkreview`. Tidak ada kode sumber, data baseline, atau tes lama yang diubah. Tidak ada commit/push.
Yang ditambah: 4 file tes baru di `tests/` dan laporan ini.

## 1. Ringkasan angka

| Ukuran | Sebelum | Sesudah |
|---|---|---|
| Tes lulus (`uv run pytest`) | 1280 | 1458 |
| Tes gagal | 2 (sudah ada sebelumnya) | 2 (sama, tidak disentuh) |
| xfail / skip | 0 / 0 | 0 / 0 |
| `ruff check .` | bersih | bersih |
| `ruff format --check .` | bersih | bersih (126 file) |
| Cakupan baris `src/wali` (pytest-cov, hanya diukur, tidak ditambahkan ke repo) | 97% (3692 stmt, 128 luput) | 98% (68 luput) |

Tes baru: +178. Semua dijalankan dan lulus. Angka di atas adalah hasil run nyata di akhir.

## 2. Inventaris fitur dan status cakupan

Cakupan = baris yang dieksekusi tes (sesudah tes baru), ditambah penilaian apakah nilai batas diuji.

| Area (src/wali) | Tes lama | Status cakupan sesudah audit |
|---|---|---|
| agent: loop, dialogue, prompts | test_agent_loop, test_dialogue, test_app | 100% baris |
| agent: llm (Anthropic), llm_openai | test_llm, test_llm_openai | 97-98%; sisa: cabang SDK tak terduga (llm.py 142-144, llm_openai.py 70-73) |
| guard: policy (11 aturan) | test_policy | 99%. Nilai batas ditambah (lihat bagian 3) |
| guard: mandate (validasi, tanda tangan) | test_mandate | 100%. Batas validasi ditambah |
| guard: service | test_guard_service, test_mandate, test_outgoing | 92% naik ke 95%. Sisa: blok `except Exception` pertahanan (audit error), `_logged_verdicts` > 10 000, beberapa cabang NotFound lingkungan |
| guard: sentinel, screening | test_sentinel, test_screening | 99% |
| guard: confirm, keys, signing, audit, store | test_confirm, test_keys, test_signing, test_audit | 94-100%. audit.py 100% sekarang |
| finance: forecast, recommend, reconcile | test_forecast, test_recommend, test_reconcile | 100% baris; nilai batas dan pembulatan ditambah |
| tools: registry, base | test_tools_registry | 99% |
| tools: sim_env | test_sim_env | 97-98%; sisa: jalur `open` gagal, seed rusak |
| tools: organiser_env (placeholder) | 1 tes | 100% (semua metode kini diuji) |
| interfaces: CLI | test_app, test_screening | 85% naik ke 99% (`main` dan pemrosesan input) |
| interfaces: web (FastAPI) | test_web | 80% naik ke 100% untuk `app.py`; `web/__main__.py` 0% (3 baris, hanya memanggil `main`) |
| interfaces: Telegram | test_telegram_bot | 96%; tidak diubah |
| app (WaliApp, build_app), config, models | test_app, test_config, test_seed_data | 100% |
| eval/ (harness, offline, dialog, compare) | test_eval_* | tes ada; 2 gagal (bagian 5) |
| scripts/gen_seed_data.py | test_seed_data | tes ada |
| frontend (Next.js) | tidak ada tes Python | lihat bagian 6 |

## 3. Tes baru

| File | Jumlah | Apa yang dikunci |
|---|---|---|
| `tests/test_money_boundaries.py` | 103 | **Policy**: batas per-pembayaran (4 999 999 / 5 000 000 / 5 000 001), batas mingguan (terpakai 14 499 999 / 14 500 000 / 14 500 001), `confirm_above` (eksklusif; 0 membuat semua pembayaran menunggu pemilik), saldo vs penyangga kas (satu unit di bawah/atas), saldo 0 dan negatif, penyangga 0, ambang 130% rata-rata pemasok (tepat 130 vs 131; rata-rata berdesimal tanpa pembulatan), batas laju per jam (9/10/11), batas peran, jumlah berdesimal, jumlah sangat besar (20 digit), jumlah 0/negatif ditolak model, digest tidak peka terhadap penulisan angka (`500000.0`, `5E+5`) tapi peka terhadap 1 sen. **Mandat**: per_payment = per_week sah, +1 ditolak; 0 ditolak untuk batas, boleh untuk `confirm_above`/buffer, negatif ditolak; mata uang campur; batas peran = batas pembayaran sah, +1 ditolak. **Forecast**: akumulasi 30 x 0,10 tanpa drift, saldo tepat di ambang bukan shortfall, saldo awal negatif/nol, horizon 1/366 sah dan 0/367 ditolak, tanggal 29 di Februari biasa vs kabisat, jumlah besar. **detect_recurring**: pembulatan harian setengah-ke-genap (0,0125 jadi 0,01; 0,0225 jadi 0,02; 0,0175 jadi 0,02), rata-rata nol dibuang, ambang 40% hari aktif, batas lookback, entri masa depan, rata-rata bulanan dibulatkan, selisih hari 1 vs 2. **Recommend**: pecah dua jumlah ganjil (101 jadi 50,5), saran yang tak mengangkat titik terendah tidak ditawarkan, `collect_in_days=0`, piutang jatuh tempo hari ini tidak dikejar, validasi argumen. **Reconcile**: selisih tepat 5% = mismatch, di atas 5% = dua item tak cocok, rasio terhadap jumlah yang lebih besar di dua arah, toleransi tepat/kurang 1 sen, rasio 0, jendela tanggal 3 hari inklusif (2, 3 cocok; 4 tidak), jendela 0, sen dan jumlah besar, batas periode inklusif. **Model**: jumlah bank/buku/recurring 0 atau negatif ditolak, format mata uang. |
| `tests/test_guard_service_gaps.py` | 23 | Entri buku lewat guard: tercatat persis (12 500,50), butuh mandat, mandat tanpa aksi `record_book_entry` ditolak, staf ditolak, faktur tak dikenal ditolak tanpa mencatat, lingkungan gagal jadi INTERNAL_ERROR, mandat kedaluwarsa. Penandaan review: lingkungan gagal, hanya pemilik melihat daftar. Draf mandat saat pencarian pemasok gagal. Batas `valid_days` (1 dan 366 sah; 0 dan 367 ditolak). Limit 0/negatif tidak sampai ke guard. Pemasok ganda ditolak. Jam guard tanpa zona waktu ditolak. Kegagalan menulis catatan guard setelah uang pindah: pembayaran tetap dilaporkan sukses dengan catatan. |
| `tests/test_interfaces_gaps.py` | 36 | CLI: sapaan, baris kosong, EOF/Ctrl-C, `/quit` dan `/exit`, nomor `/confirm`/`/cancel` harus bilangan bulat positif (0, -1, 1.5, abc, "1 2" ditolak), item tak ada, bookkeeper tak bisa `/mandate`, `/review` kosong, garis miring di tengah pesan tetap obrolan, `main` (gagal setup jadi kode 1, peran terpilih diteruskan, peran tak dikenal keluar kode 2). Web: peran tak ada di bisnis jadi 404 dan tak tercantum, peran/parameter tak valid 422, id tak dikenal 404, panjang `subject_id` 1-100, pesan tepat 4000 karakter diterima, draf mandat gagal jadi 503 tanpa membocorkan detail, header keamanan ada juga di jawaban galat, POST non-JSON ditolak 403, `main` (host lokal tanpa peringatan, host lain memperingatkan tak ada login, gagal setup jadi kode 1; server uvicorn diganti palsu). Placeholder organiser: ketujuh metode melempar NotImplementedError. |
| `tests/test_edges_misc.py` | 16 | Membayar faktur senilai tepat saldo berhasil dan menyisakan 0; saldo kurang 1 ditolak tanpa mengubah apa pun. Persetujuan sah 1 mikrodetik sebelum kedaluwarsa. Jam bank tanpa zona waktu jadi galat, bukan pembayaran. Timestamp tanpa zona waktu ditolak GuardStore. Log audit dengan float disisipkan dilaporkan tidak valid di baris 1. Batas inklusif 8 pengaturan (`WALI_AGENT_MAX_STEPS` dll.) dan satu langkah di luarnya ditolak. Parsing `.env`: tanda `=` di nilai, kutip luar. |

Tes tidak memanggil model nyata maupun jaringan. Memakai `ScriptedLLM`, fixture `world`/`ready`, dan `TestClient` seperti tes lain.

## 4. LULUS (benar-benar dijalankan)

- `uv run pytest`: 1458 lulus.
- `uv run ruff check .`: bersih. `uv run ruff format --check .`: 126 file sudah terformat.
- `npm run lint` di `frontend/`: keluar dengan kode 0, tanpa pesan.

## 5. GAGAL

Dua kegagalan yang sudah ada sebelum audit, tidak diperbaiki (sesuai instruksi), keduanya di `tests/test_eval_offline.py`.

| Tes | Penyebab (diverifikasi dengan menjalankan `eval.offline`) |
|---|---|
| `test_the_stored_offline_baseline_is_up_to_date` | `docs/baseline/offline.json` basi. `eval/attacks.yaml` sekarang memuat 25 serangan (A001-A025), baseline tersimpan 20. 17 selisih: `attacks.count` 20 jadi 25, `attacks.held` 20 jadi 25, dan untuk A021-A025 masing-masing `broken_when_showing_data`, `broken_when_showing_prompt`, `category` hilang dari baseline. |
| `test_what_plain_code_guarantees_holds_without_any_model` | Menegaskan `count == 20`, nyatanya 25 (`assert 25 == 20`). Angka 20 di-hardcode. |

Catatan penting: bukan kode yang memburuk. Hasil baru menunjukkan **25 dari 25 serangan tertahan** (`held == count`). Hanya baseline dan satu angka di tes yang tertinggal setelah lima serangan baru ditambahkan. Perbaikannya butuh keputusan pengguna karena menyentuh `docs/baseline/` (data baseline dilarang diubah di tahap ini) dan mengubah tes yang ada.

## 6. BELUM BISA DIUJI

| Hal | Alasan |
|---|---|
| `npm run typecheck` | **Gagal karena lingkungan, bukan kode**: `lucide-react` (tercantum di `package.json` dan `package-lock.json`, versi 1.58.0) tidak ada di `frontend/node_modules`. Tiga error TS2307 di `components/landing/landing-interactions.tsx`, `landing-page.tsx`, `workflow-demo.tsx`. Tidak ada error tipe lain. `npm install` tidak dijalankan sesuai instruksi. Perlu `npm ci` agar hasilnya bermakna, dan CI perlu dicek apakah lolos. |
| `frontend/scripts/verify-*.cjs` (12 skrip, `npm run test:*`) | Tidak dijalankan. Butuh browser Chromium lewat Playwright dan server Next di `http://127.0.0.1:3005` (`WALI_TEST_ORIGIN`). Paket `playwright` ada di node_modules, tapi tidak ada server maupun browser yang disiapkan. |
| Panggilan model sungguhan (Anthropic, OpenAI-compatible) | Butuh API key dan jaringan. Kontrak diuji hanya dengan SDK palsu (test_llm, test_llm_openai). |
| Evaluasi dengan model (`eval/` run per model, dialog nyata, `docs/baseline` per model) | Butuh model nyata. Hanya lapisan tanpa model (`eval.offline`) yang diuji. |
| Bot Telegram nyata | Butuh token BotFather dan jaringan. `run_polling` diganti palsu. |
| Server web nyata (`uvicorn`, `web/__main__.py`) | Server tidak dinyalakan. `main` diuji dengan `uvicorn.run` palsu. `__main__.py` (3 baris) tidak tercakup. |
| `OrganiserEnvironment` | Belum diimplementasi (API penyelenggara tidak diketahui, `docs/assumptions.md` U1). Hanya diuji bahwa ia menolak dengan jelas. |
| Jalur `except Exception` pertahanan di `guard/service.py` (mis. baris 1042-1044, 1067-1069, 1231-1233, 1341-1343, 1432-1434) | Butuh injeksi galat internal acak. Bukan dilakukan karena akan menguji detail implementasi, dan tiap jalur hanya menulis audit lalu menolak. |

## 7. Temuan (potensi bug atau perilaku tampak pengguna). Tidak ada yang diperbaiki.

| # | Temuan | Tingkat | Tindakan |
|---|---|---|---|
| F1 | Baseline offline dan tes `== 20` basi (bagian 5). | Sedang (suite merah) | Butuh keputusan pengguna. |
| F2 | Penolakan saldo kurang memakai kode `BELOW_CASH_BUFFER`, padahal melanggar penyangga kas hanya peringatan dan konfirmasi pemilik. Satu kode dua arti: "saldo tidak cukup" (tolak) vs "di bawah penyangga" (peringatan). Pesan penolakan sudah benar ("The balance is not enough"). Terkunci di tes saat ini. | Rendah | Kandidat ganti nama kode (mengubah audit/eval), tunggu keputusan. |
| F3 | Pesan `/mandate` di CLI tidak konsisten per peran: staf menerima "Only the owner can set the mandate." (dari pengecualian lingkungan), bookkeeper menerima "guard> Only the owner can set or change the spending mandate." (dari guard). Keduanya aman, teks beda. | Rendah, tampak pengguna | Catat. |
| F4 | `detect_recurring` membulatkan rata-rata harian/bulanan dengan `Decimal.quantize` bawaan, yaitu setengah-ke-genap (0,0125 jadi 0,01, bukan 0,02). Dengan rupiah tanpa sen, rata-rata dibagi hari kalender menghasilkan nilai bersen (mis. 333 333,33) di proyeksi. Konsisten tapi mungkin mengejutkan. | Rendah | Terkunci. Tentukan apakah rupiah perlu dibulatkan ke satuan. |
| F5 | Rekomendasi `delay_payable` dan `split_payment` hanya muncul jika menunda benar-benar mengangkat titik terendah. Bila saldo tetap rendah setelah jendela tunda (tanpa pemasukan susulan), tidak ada saran, walau menunda tetap memberi napas. Sesuai komentar kode (by design), tapi bisa mengejutkan pemilik dalam kondisi kas tipis. | Rendah | Catat. |
| F6 | Aritmetika `Decimal` memakai presisi bawaan 28 digit. Jumlah lebih dari 28 digit akan dibulatkan diam-diam di forecast/policy, dan model tidak membatasi ukuran jumlah. Tidak realistis untuk rupiah, tetapi tak ada batas atas yang eksplisit pada `PositiveAmount`/`MandateRequest`. Tes memakai 20 digit. | Rendah | Pertimbangkan batas atas. |
| F7 | Urutan aturan: batas laju (aturan 10) dicek setelah batas jumlah/saldo. Pemanggil yang kena batas laju tetap melihat penolakan batas jumlah lebih dulu. Sesuai dokumen, bukan bug. | Info | - |
| F8 | `frontend/next-env.d.ts` berstatus modified sebelum audit dimulai (path impor `.next/dev/types/` ditulis ulang oleh `next dev`). Bukan dari audit ini. | Info | Putuskan apakah dikembalikan sebelum merge. |

Tidak ditemukan bug yang jelas salah pada logika uang. Semua nilai batas dan pembulatan yang diuji sesuai dokumentasi di docstring modul (tidak ada tes yang ditandai xfail).

## 8. Rekomendasi tahap berikut

1. Putuskan perbaikan F1: simpan ulang baseline offline (`uv run python -m eval.offline --write`) dan ganti angka 20 di tes dengan jumlah kasus dari `attacks.yaml`, atau hentikan hardcode. Perlu persetujuan karena mengubah `docs/baseline/` dan tes lama.
2. Jalankan `npm ci` di `frontend/`, lalu `npm run typecheck`, `npm run lint`, `npm run format:check`, dan cek apakah CI hijau.
3. Jalankan skrip `verify-*.cjs` dengan Playwright dan `next start` di port 3005 (tahap UI/aksesibilitas).
4. Tinjau keamanan: penyaringan teks tak tepercaya, rahasia di log, CSRF web (sudah ada tes dasar), mandat/tanda tangan, rate limit, sudah punya tes; fokus pada audit konfigurasi dan dependensi (`uv`/`npm audit`).
5. Putuskan F2, F3, F4, F6 sebagai perubahan kecil bila diinginkan (tiap satu commit dengan tes, dan hentikan untuk bertanya bila tampak pengguna).
6. Evaluasi dengan model nyata bila ada kunci API; baseline per model di luar cakupan tahap ini.
