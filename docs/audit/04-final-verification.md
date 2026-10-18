# Audit tahap 4: verifikasi akhir

Branch `checkreview` (HEAD `0b3b4f5`). Tahap ini hanya memverifikasi. Tidak ada kode, tes, atau data yang diubah.
Satu-satunya file baru adalah laporan ini.

## Keputusan: **NO-GO**

Branch ini belum boleh dirilis atau dipakai di luar demo. Alasannya:

1. **11 dari 13 item Critical/Required belum dikerjakan** (#3 sampai #13). Semuanya masih menunggu keputusan
   pemilik karena tampak pengguna. Termasuk di dalamnya celah yang bisa membuat batas mingguan terlewati (#3, #4, #5)
   dan injeksi yang lolos penyaring (#7, #8).
2. **Perbaikan #1 membawa regresi baru.** Akses FastAPI lewat `[::1]` sekarang ditolak 400 (lihat R1).
3. **Ada perubahan perilaku yang belum disetujui.** Akses lewat IP LAN sekarang ditolak (lihat R2). `03-fixes.md`
   sendiri menulis "belum diputuskan apakah itu diterima".
4. **Suite Python tidak hijau.** 2 tes gagal (F1). Kegagalan ini sudah ada di `main`, tetapi job `pytest` di CI
   tetap merah.

Dua perbaikan yang sudah ada (#1, #2) benar arahnya dan tidak memperburuk keamanan dibanding `main`. Kalau R1 sudah
diperbaiki dan R2 sudah diputuskan, keduanya aman di-merge sebagai langkah parsial. Merge itu **bukan** go untuk rilis.

## Dasar pembanding

- Tag `audit-baseline` **tidak ada**, baik di lokal maupun di `origin` (hanya ada `v1.0.0`). Sebagai baseline dipakai
  merge-base `checkreview` dan `main`, yaitu `38d29ea`.
- `main` tidak bergerak sejak branch dibuat (`git log checkreview..main` kosong). Jadi pembandingan dengan baseline
  dan dengan `main` menghasilkan diff yang sama: 10 commit, 18 file, +1850/-16.
- Kalau `audit-baseline` memang dimaksudkan untuk commit lain (misalnya `9e8dcb4`, commit aturan audit), laporan ini
  perlu dicek ulang terhadap commit tersebut.

## (1) Status item Critical dan Required dari `02-review.md`

| # | Severity | Status | Bukti |
|---|---|---|---|
| 1 | Critical | **Teratasi, dengan regresi** | `5e943e7`. Host `evil.example` ditolak (GET 400, POST 403), dan tidak ada pembayaran yang tercipta. Ini dibuktikan oleh `test_a_website_that_rebinds_its_name_to_this_computer_is_refused` dan 6 tes `local-request.test.ts`. Di proxy, GET sekarang juga dicek. Regresinya ada di R1. |
| 2 | Required | **Teratasi** | `775ac0f`. `next.config.ts` mengirim `frame-ancestors 'none'`, `X-Frame-Options: DENY`, dan `nosniff` untuk `/:path*`. Dibuktikan oleh `next-config.test.ts` (2 tes). Header hanya diuji dari objek konfigurasi, belum lewat `next start` (lihat R6). |
| 3 | Required | **Belum** | Menunggu keputusan pemilik. |
| 4 | Required | **Belum** | Menunggu keputusan. Perilaku lama masih dikunci oleh `test_a_failure_writing_the_guards_own_record_is_noted_but_the_payment_stands`. |
| 5 | Required | **Belum** | Menunggu keputusan. |
| 6 | Required | **Belum** | Menunggu keputusan. |
| 7 | Required | **Belum** | Menunggu keputusan. |
| 8 | Required | **Belum** | Menunggu keputusan. |
| 9 | Required | **Belum** | Menunggu keputusan. |
| 10 | Required | **Belum** | Menunggu keputusan. |
| 11 | Required | **Belum** | Menunggu keputusan. |
| 12 | Required | **Belum** | Menunggu keputusan. |
| 13 | Required (risiko diterima) | **Belum** | Risiko diterima untuk demo. Tetap jadi penghalang untuk pemakaian di luar demo. |

## (2) Isi diff: hanya tes dan perbaikan?

**Ya, tidak ada fitur baru.** Rinciannya:

- **Tes tahap 1** (`54da59d`, `3903ec4`, `412866c`, `2a6ea2f`): hanya menambah file di `tests/`. Tidak ada kode sumber
  yang disentuh, dan tidak ada `skip` atau `xfail` baru.
- **Perbaikan #1** (`5e943e7`): `web/app.py`, `route.ts`, dan modul baru `lib/local-request.ts`, beserta tesnya.
  Perubahan `tsconfig.json` (`allowImportingTsExtensions`) dan skrip `test:unit` di `package.json` hanya untuk
  menjalankan tes. Tes lama di `test_web.py` dan `test_interfaces_gaps.py` diubah dari `Origin: http://testserver`
  ke host lokal. Ini wajar karena `testserver` memang bukan host lokal.
- **Perbaikan #2** (`775ac0f`): `next.config.ts` beserta tesnya.
- **Dokumen**: `AGENTS.md` (aturan audit), `CLAUDE.md`, dan `docs/audit/01` sampai `03`.
- Tiap perbaikan berada di satu commit kecil beserta tesnya, sesuai aturan.

**Ada perubahan perilaku yang belum disetujui:**

- **R2, akses lewat nama host selain loopback ditolak.** Ini berlaku di FastAPI maupun di proxy Next. Siapa pun yang
  membuka frontend lewat `http://192.168.0.13:3000` (IP yang tercantum di `allowedDevOrigins`) sekarang mendapat 403
  dari setiap panggilan `/api/wali/*`. `03-fixes.md` mencatat hal ini tetapi belum ada keputusan. Menurut `AGENTS.md`,
  perubahan seperti ini harus ditanyakan dulu.
- **R1, `[::1]` ditolak.** Ini bug, bukan perubahan yang disengaja. `03-fixes.md` menyatakan `[::1]` tidak berubah,
  padahal kenyataannya berubah.

## (3) Hasil tes

Dijalankan di HEAD `0b3b4f5`, dengan `frontend/next-env.d.ts` termodifikasi (F8, tidak berpengaruh ke tes).

| Pemeriksaan | Hasil | Di `main` (`38d29ea`) |
|---|---|---|
| `uv run pytest -q` | **1459 lulus, 2 gagal** | 1280 lulus, 2 gagal (dua tes yang sama) |
| `ruff check` / `ruff format --check` | bersih | - |
| `npm run test:unit` (Node 22.23) | 8 lulus, 0 gagal | belum ada |
| `npx eslint app/api lib next.config.ts` | bersih | - |
| `npx tsc --noEmit` | 3 error `lucide-react` tidak ditemukan | sama (paket tercantum di `package.json` tetapi tidak terpasang di `node_modules` lokal) |
| `npm audit --omit=dev` | 0 kerentanan | - |
| `uvx pip-audit` (90 dependensi produksi dari `uv export --frozen --no-dev`) | **tidak ada kerentanan yang diketahui** | - |

Kedua kegagalan (`test_eval_offline.py::test_the_stored_offline_baseline_is_up_to_date` dan
`test_what_plain_code_guarantees_holds_without_any_model`) adalah F1: `attacks.yaml` sudah berisi 25 serangan,
tetapi baseline dan tes masih menulis 20. Hasilnya sendiri **25 dari 25 tertahan**, jadi tidak ada regresi
keamanan. Meski begitu, kriteria "seluruh tes lulus" **tidak terpenuhi**.

Yang tidak dijalankan: skrip Playwright (`test:ui`, `test:landing`, dan seterusnya) dan `next build`, karena
butuh browser serta `node_modules` yang lengkap. Job CI juga tidak menjalankan `test:unit`, jadi tes frontend
baru belum dijaga CI (R5).

## (4) Celah baru

Kode baru dicoba langsung dengan `TestClient` terhadap `create_web_app`, memakai file tes sementara yang
sudah dihapus lagi:

| Percobaan | Hasil |
|---|---|
| `GET /api/info` dengan `Host: [::1]:8000` | **400** (R1) |
| `GET` dengan `Host: localhost.evil.example` | 400 |
| `POST` dengan `Origin: http://localhost:1234` (port lain) | 200 (R3) |
| `POST` dengan `Origin: https://127.0.0.1` (skema lain) | 200 (R3) |
| `POST` dengan `Origin: null` atau `http://0.0.0.0` | 403 |
| `--host 0.0.0.0`, `Host: 0.0.0.0:8000` | 200 |
| `--host 0.0.0.0`, `Host: 192.168.0.13:8000` | 400 (R2) |

**Tidak ditemukan celah baru yang bisa dieksploitasi.** Yang ditemukan adalah satu regresi fungsi dan satu
pelonggaran pertahanan berlapis:

- **R1 (regresi):** di `src/wali/interfaces/web/app.py:37`, `LOCAL_HOSTS` berisi `"::1"`. Padahal
  `TrustedHostMiddleware` (Starlette) mengurai `[::1]:8000` menjadi host `"[::1]"` dengan kurung siku, jadi
  keduanya tidak pernah cocok. Akibatnya, akses lewat `http://[::1]:8000/` ditolak, dan `--host ::1` membuat server
  tidak bisa dipakai sama sekali. Pengecekan Origin di baris 88 justru cocok, karena `urlsplit` membuang kurung
  siku. Proxy Next (`lib/local-request.ts:3`) sudah benar karena memakai `"[::1]"`. Tidak ada tes FastAPI untuk IPv6.
- **R3 (pelonggaran):** `main` mewajibkan Origin sama persis dengan skema dan port, sedangkan sekarang cukup
  hostname-nya lokal (`app.py:88`, `local-request.ts:17-18`). Pelonggaran ini tidak bisa dieksploitasi dari browser.
  Halaman di port lain tetap lintas origin, dan POST JSON butuh preflight CORS. FastAPI menolak `OPTIONS` (403),
  dan tidak ada header CORS. Namun lapisan pengecekan Origin sekarang lebih lemah dari sebelumnya.

## Daftar sisa risiko

| # | Risiko | Severity | Asal | Yang perlu dilakukan |
|---|---|---|---|---|
| — | Item #3 sampai #12 belum diperbaiki | Required | `02-review.md` | Pemilik menjawab pertanyaan di `03-fixes.md`, lalu tiap item dikerjakan satu commit beserta tes. |
| — | #13: web tanpa login | Required (diterima untuk demo) | `02-review.md` | Jangan jalankan di luar loopback atau `--host 0.0.0.0` sebelum ada login atau token per peluncuran. |
| R1 | `[::1]` ditolak oleh FastAPI | **Selesai** (`e38bfd6`) | `5e943e7` | Host IPv6 diberi kurung siku sebelum diserahkan ke `TrustedHostMiddleware`. Tes `test_every_local_host_name_reaches_the_api` gagal untuk `[::1]:8000` dan `[::1]` sebelum perbaikan, lalu lulus sesudahnya. |
| R2 | Akses lewat IP LAN ditolak | Keputusan pemilik | `5e943e7` | Putuskan apakah diterima. Kalau ya, catat di `03-fixes.md` dan hapus `192.168.0.13` dari `allowedDevOrigins` (#30). Kalau tidak, allowlist harus bisa dikonfigurasi. |
| R3 | Port dan skema Origin tidak dicek | Nit (defense-in-depth) | `5e943e7` | Bandingkan origin lengkap (skema, host, dan port) dengan daftar yang dikonfigurasi. Ini sejalan dengan #20. |
| R4 | 2 tes gagal (F1), CI `pytest` merah | Required (proses) | sudah ada sebelum audit | Perlu keputusan pemilik: tulis ulang `docs/baseline/offline.json` dan ganti angka 20 di tes. |
| R5 | `test:unit` tidak dijalankan di CI | Nit | `5e943e7`, `775ac0f` | Tambahkan langkah `npm run test:unit` di job frontend `ci.yml`. Node 22 di CI sudah mendukung `node --test` untuk `.ts`. |
| R6 | Header anti-clickjacking belum dicek di server sungguhan | Nit | `775ac0f` | Jalankan `next build && next start`, lalu `curl -I` halaman `/approvals`. |
| R7 | `frontend/next-env.d.ts` termodifikasi (F8) | Nit | lingkungan | `git checkout -- frontend/next-env.d.ts` sebelum merge. |
| R8 | Item Optional/Nit #14 sampai #37 | Optional/Nit | `02-review.md` | Tidak dikerjakan di tahap ini. #37 (pip-audit) sekarang sudah dicek manual dan hasilnya bersih, tetapi belum masuk CI. |
| R9 | Tag `audit-baseline` tidak ada | Proses | - | Buat tag pada commit yang dimaksud (kemungkinan `38d29ea`), supaya audit berikutnya bisa dibandingkan dengan titik yang sama. |

## Rollback

Branch belum di-merge, jadi tidak ada yang perlu di-rollback. Kalau #1 dan #2 di-merge lalu bermasalah,
`git revert 775ac0f 5e943e7` mengembalikan perilaku `main`. Tidak ada migrasi data, karena `data/`, `guard.db`,
dan log audit tidak disentuh.

## Syarat menjadi GO

1. #3 sampai #12 diperbaiki, masing-masing beserta tes, setelah pemilik memutuskan.
2. R2 diputuskan (R1 sudah diperbaiki di `e38bfd6`).
3. `uv run pytest` lulus 100% (F1 sudah diputuskan) dan `test:unit` berjalan di CI.
4. #13 diputuskan: login atau token sebelum dipakai di luar demo, atau pemakaian dibatasi tegas hanya untuk demo lokal.

## Pembaruan setelah laporan

- **R1 diperbaiki** di `e38bfd6`. Setelah perbaikan, `uv run pytest -q` menghasilkan 1463 lulus dan 2 gagal. Dua
  kegagalan itu sama dengan F1, sedangkan 4 tes baru semuanya lulus. `ruff` bersih.
- Keputusan tetap **NO-GO**. Item #3 sampai #13, R2, dan F1 belum selesai.
