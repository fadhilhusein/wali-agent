# Audit tahap 3: perbaikan

Branch `checkreview`. Sumber daftar: `docs/audit/02-review.md`.
Aturan (`AGENTS.md`): tidak menambah fitur, satu perbaikan = satu commit kecil beserta tes,
dan perbaikan yang mengubah perilaku yang tampak pengguna ditanyakan dulu.

## Status item Critical dan Required

| # | Severity | Status | Commit | Catatan |
|---|---|---|---|---|
| 1 | Critical | **Selesai** | `5e943e7` | DNS rebinding. Lihat rincian di bawah. |
| 2 | Required | **Selesai** | `775ac0f` | Header anti-clickjacking di Next. |
| 3 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 4 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 5 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 6 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 7 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 8 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 9 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 10 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 11 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 12 | Required | Menunggu keputusan | - | Tampak pengguna: **YA**. Belum dikerjakan. |
| 13 | Required (risiko diterima) | Menunggu keputusan | - | Tampak pengguna: **YA**. Menyangkut login. Lihat catatan. |

Item Optional, Nit, dan FYI tidak dikerjakan pada tahap ini.

## #1: DNS rebinding (Critical)

**Masalah yang dibuktikan dengan tes.** `GET /api/pending?role=owner` dengan header `Host: evil.example`
menghasilkan 200, dan `POST /api/confirm` dengan `Host` dan `Origin` `evil.example` menjalankan pembayaran.
Proxy Next juga tidak memeriksa GET sama sekali. Karena proxy meneruskan ke `127.0.0.1:8000` dengan
Host-nya sendiri, GET lewat proxy bisa dibaca dari halaman jahat.

**Perbaikan.**
- FastAPI (`src/wali/interfaces/web/app.py`): `TrustedHostMiddleware` dengan allowlist `127.0.0.1`,
  `localhost`, `::1`, dan nilai `--host`. Origin dibandingkan dengan daftar host ini, bukan dengan header Host.
- Proxy (`frontend/lib/local-request.ts`, dipakai di `route.ts`): Host dan Origin dicek untuk GET dan POST.

**Tes.**
- `tests/test_web.py::test_a_website_that_rebinds_its_name_to_this_computer_is_refused`:
  gagal sebelum perbaikan (`200 == 400`), lulus sesudahnya (400 untuk GET, 403 untuk POST).
- `frontend/lib/local-request.test.ts`: 6 tes. Dijalankan dulu saat modul belum ada (gagal), lalu lulus.
- Tes lama yang memakai `Origin: http://testserver` diganti ke host lokal, dan helper TestClient memakai
  `base_url` `http://127.0.0.1:8000` supaya sama dengan kondisi nyata.

**Perubahan yang tampak.** Untuk pemakaian lokal bawaan (`127.0.0.1`, `localhost`, `[::1]`) tidak ada perubahan.
Akses dengan nama host lain, misalnya lewat IP LAN `192.168.0.13` (yang ada di `allowedDevOrigins`), sekarang
ditolak. Untuk `--host 0.0.0.0`, akses lewat IP LAN juga ditolak kecuali nilai yang sama dengan `--host`.
Ini konsekuensi dari perbaikan, dan belum diputuskan apakah itu diterima.

## #2: header anti-clickjacking (Required)

**Perbaikan.** `frontend/next.config.ts` menambahkan `headers()` untuk `/:path*`:
`Content-Security-Policy: frame-ancestors 'none'`, `X-Frame-Options: DENY`, dan `X-Content-Type-Options: nosniff`.

**Tes.** `frontend/lib/next-config.test.ts`: 2 tes, gagal sebelum perbaikan, lulus sesudahnya.
Tidak ada iframe di frontend, jadi tidak ada halaman yang berubah.

## Hasil tes

Dijalankan setelah commit `775ac0f`:

- `uv run pytest -q`: **1459 lulus, 2 gagal**. Dua kegagalan (`test_eval_offline.py::test_the_stored_offline_baseline_is_up_to_date`
  dan `test_what_plain_code_guarantees_holds_without_any_model`) sudah ada sebelum perubahan ini, dan tercatat
  sebagai F1 (baseline offline basi) di `02-review.md`. Sebelum perubahan, hasilnya juga 1458 lulus dan 2 gagal.
- `uv run ruff check src tests scripts eval` dan `ruff format --check`: bersih.
- `npm run test:unit` (frontend): **8 lulus, 0 gagal**.
- `npx eslint` untuk file yang diubah: bersih.
- `npx tsc --noEmit`: tidak ada error dari file yang diubah. Tiga error tersisa
  (`lucide-react` tidak ditemukan) sudah ada karena paket itu tidak terpasang di `node_modules`.
- Skrip Playwright (`npm run test:*`) dan `next build` **tidak dijalankan**. Keduanya butuh browser atau
  dependensi yang tidak lengkap di lingkungan ini.

`frontend/next-env.d.ts` masih termodifikasi oleh `next dev` (F8), dan sengaja tidak ikut commit.

## Perlu keputusan pemilik

Item di bawah mengubah perilaku yang tampak pengguna, sehingga belum dikerjakan:

- **#3** (pembayaran diulang saat timeout): tanya cara membedakan "gagal" dan "belum pasti". Apakah bank bisa dicek ulang lewat faktur?
- **#4** (batas mingguan): gagal tertutup (tolak pembayaran berikutnya sampai catatan cocok), atau hitung dari nilai terbesar antara catatan guard dan bank?
- **#5** (tiga antarmuka berbagi `data/`): batasi satu proses per folder, atau pakai file lock?
- **#6** (koreksi dengan dua pembayaran): hanya usulan kedua yang tersisa, atau keduanya tetap menunggu?
- **#7** (teks tak tersaring dianggap CLEAN): tandai "belum disaring" dan minta pemilik, atau cara lain?
- **#8** (entri buku tanpa konfirmasi): tolak entri di giliran mencurigakan saja, atau juga minta konfirmasi di atas ambang?
- **#9** (permintaan hilang saat lingkungan tidak bisa dihubungi): kembalikan ke inbox?
- **#10** (`/confirm n` memakai nomor yang bisa bergeser): simpan pemetaan nomor per daftar?
- **#11** (UI menampilkan penolakan dengan warna sukses): warna ditentukan dari `status`?
- **#12** (catatan "mungkin sudah dibayar" hanya saat `LLMError`): tambahkan juga di batas langkah dan penolakan model?
- **#13** (web tanpa login, risiko diterima): apakah login atau token rahasia per peluncuran dibuat sebelum
  dipakai di luar demo? Ini mengubah cara pemilik masuk, jadi perlu persetujuan Anda.

Sebelum ke #3, #4, dan seterusnya, saya perlu jawaban untuk pertanyaan di atas.
