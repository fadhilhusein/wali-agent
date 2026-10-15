# Rencana Finalisasi Wali

Disusun 2026-10-15 berdasarkan `PROJECT_AUDIT.md`.

**Kondisi awal git:**
- `origin/main` dan `origin/update` menunjuk ke commit yang sama (`9c05ff0`).
- Commit lokal `bbadcd3` di branch `update` tidak tersambung ke riwayat itu (orphan).
- Branch `main` belum ada di lokal.

**Alur kerja untuk semua fase:**
1. Kerjakan di branch `update`.
2. Buka PR dari `update` ke `main`.
3. Merge setelah tes hijau. Satu PR berisi satu topik.

---

## Fase 0: Rapikan git (hari 1, wajib paling awal)

Tujuan: branch `update` lokal kembali tersambung dengan riwayat `main`.

```bash
git branch backup/orphan-update          # jaga-jaga
git fetch origin
git reset --mixed origin/main            # isi file tidak berubah, hanya riwayat dibetulkan
git rm --cached wali-agent 2>/dev/null; echo "wali-agent/" >> .gitignore
git status                               # harusnya hanya .gitignore, PROJECT_AUDIT.md, dan docs/FINALIZATION_PLAN.md
```

Sebelum menghapus folder `wali-agent/`, tanyakan dulu ke pemilik repo apakah folder itu masih dipakai.

**Selesai jika:**
- `git log` menampilkan 15 commit Phase 0–8.
- `git push origin update` berjalan tanpa `--force`.

---

## Fase 1: Lingkungan dan baseline (hari 1–3)

1. Backend Python:
   - pasang `uv` dan Python 3.11;
   - jalankan `uv sync`, `make test`, dan `make lint`;
   - catat hasilnya.
2. Frontend:
   - pasang Node 20.9 atau lebih baru;
   - di `frontend/`, jalankan `npm ci`, `npm run typecheck`, dan `npm run lint`.
3. Konfigurasi:
   - `cp .env.example .env`;
   - `make key`;
   - isi model dan API key di `.env`.
4. Baseline evaluasi (memakai kredit API):
   - jalankan `make live-check`, lalu `make eval`;
   - simpan laporan dari `eval/reports/` sebagai **baseline**.
5. Coba demo manual lewat CLI, lalu web ditambah frontend, mengikuti `README.md:111-121`.

**Selesai jika:**
- tes hijau;
- ada angka baseline eval;
- demo jalan di mesin sendiri.

Kalau ada tes yang gagal, catat dulu. Jangan langsung diperbaiki.

---

## Fase 2: Klarifikasi (paralel dengan Fase 1)

Tanyakan ke tim atau panitia (lihat §14 `PROJECT_AUDIT.md`):

- deadline dan format submission (U3);
- apakah panitia menyediakan environment beserta API-nya (U1), dan cara penilaiannya (U2);
- model dan provider yang dipakai saat demo, serta apakah aturan lomba mengizinkannya;
- persetujuan keputusan C63 (sentinel per-record) dan C79 (satu akun Telegram memegang dua role);
- angka nyata `MANUAL_MINUTES_PER_ITEM` (U5).

**Selesai jika:** semua jawaban dicatat di `docs/assumptions.md`. Jawaban ini menentukan apakah Fase 6 perlu dikerjakan.

---

## Fase 3: CI sebagai gerbang kualitas (minggu 1)

1. Tambahkan `.github/workflows/ci.yml` yang menjalankan:
   - backend: `uv sync`, `pytest`, `ruff check`, `ruff format --check`;
   - frontend: `npm ci`, `typecheck`, `lint`.
2. CI **tidak** boleh menjalankan eval atau live-check, karena keduanya memakai kredit API.
3. Aktifkan branch protection di `main`: wajib PR dan CI hijau.

**Selesai jika:** setiap PR dari `update` ke `main` otomatis dites.

---

## Fase 4: Perbaikan keandalan (minggu 2)

Urutan di bawah mengikuti prioritas. Satu butir sebaiknya satu PR.

1. **Audit log saat beberapa proses berjalan** (`src/wali/guard/audit.py`). Pilih salah satu:
   - tambahkan file lock dan baca hash terakhir sebelum menulis; atau
   - pasang aturan "satu proses per folder data" yang dicek saat start.
2. **Proxy Next** (`frontend/app/api/wali/[action]/route.ts`):
   - tambahkan timeout, misalnya `AbortSignal.timeout(130_000)`;
   - perbaiki cek Origin yang di-hardcode `http://`.
3. **`allowedDevOrigins`** (`frontend/next.config.ts:4`): pindahkan IP yang di-hardcode ke env.
4. **Antrian approval** (`frontend/components/workspace-provider.tsx`):
   - tambahkan polling ringan;
   - satukan kode `loadPending` yang terduplikasi.
5. **Fallback Anthropic:**
   - pastikan beta fallback berfungsi dengan live-check;
   - kalau ragu, set default `WALI_LLM_REFUSAL_FALLBACK=false`.

**Selesai jika:**
- semua tes hijau;
- `eval --suite attacks` tetap menghasilkan 0 serangan yang lolos.

---

## Fase 5: Bersih-bersih (minggu 2–3)

1. Hapus kode mati di frontend:
   - `@fontsource/outfit`, `clsx`, `tailwind-merge`;
   - `frontend/lib/utils.ts`;
   - selector CSS lama di `frontend/app/globals.css`.

   Verifikasi dengan skrip `npm run test:*`.
2. Putuskan nasib UI statis lama (`src/wali/interfaces/web/static/`): dipertahankan sebagai cadangan, atau dihapus.
3. Tulis ulang `frontend/README.md` agar tidak bergantung pada path Windows.

---

## Fase 6: Adapter environment panitia (hanya jika Fase 2 menyatakan perlu)

1. Implementasikan `src/wali/tools/organiser_env.py` sesuai protocol di `src/wali/tools/base.py`.
2. Hormati aturan yang sudah ada:
   - verifikasi role di setiap pemanggilan;
   - `execute_payment` hanya menerima approval yang bertanda tangan;
   - retry `execute_payment` harus ditinjau ulang (C36), karena dengan sistem nyata retry tidak lagi aman.
3. Tambahkan tes kontrak yang dijalankan untuk `SimEnvironment` dan adapter baru sekaligus.

---

## Fase 7: Hardening keamanan (minggu 3)

1. Jalankan `pip-audit` dan `npm audit`, lalu perbarui dependensi yang rentan.
2. Tambahkan CSP dan header keamanan di Next lewat `next.config.ts` `headers()`.
3. **Jika demo harus bisa diakses dari luar laptop:** tambahkan autentikasi minimal, misalnya token per role dari env. Sebelum itu ada, tetap localhost saja.
4. Pastikan `.env` tidak pernah ter-commit: `git log --all -- .env` harus kosong.

---

## Fase 8: Evaluasi final (minggu 3–4)

1. Masukkan angka `MANUAL_MINUTES_PER_ITEM` yang asli.
2. Jalankan `uv run python -m eval.run_eval --suite all --repeat 3`.
3. Bandingkan hasilnya dengan baseline model yang sama dan target di `eval/report.py:23-49`. `make eval` mencetak perbandingan ini otomatis. Kalau model demo belum punya baseline, yang dipakai target saja, dan `make baseline-offline` tetap berlaku (lihat `docs/baseline/README.md`):
   - task success ≥ 0.9
   - attack success = 0
   - reconciliation F1 ≥ 0.9
4. Jika ada metrik di bawah target, perbaiki prompt atau logika, lalu jalankan eval ulang setiap selesai mengubah.

---

## Fase 9: Packaging dan dokumentasi (minggu 4)

README sendiri menjanjikan isi ini untuk "phase 10" (`README.md:27-29`).

1. Update tabel status di `README.md` menjadi fase 9–10 selesai.
2. Tambahkan ke README:
   - deskripsi arsitektur (bisa diambil dari §4 `PROJECT_AUDIT.md`);
   - daftar pihak ketiga;
   - **naskah demo**.
3. Pertimbangkan Dockerfile atau `make demo` agar juri bisa menjalankan project dengan satu perintah.
4. Merge ke `main`, lalu buat tag `v1.0.0`.

---

## Fase 10: Gladi demo dan submit

1. Mulai dari clone bersih `main`, lalu ikuti README dari nol. Ini cara menguji apakah README benar-benar lengkap.
2. Gladi skenario berikut:
   - pembayaran kecil yang langsung dibayar;
   - pembayaran besar yang menunggu konfirmasi owner;
   - serangan invoice `inv-0094`;
   - tool gagal lewat `/simfail`.
3. Siapkan cadangan:
   - cara reset folder `data/`;
   - rekaman video demo;
   - API key kedua.
4. Kirim submission sesuai format yang didapat di Fase 2.

---

## Urutan minimum kalau waktunya sempit

Fase 0 → 1 → 2 → 8 → 9 → 10.

Fase 3–7 dikerjakan sesuai sisa waktu. Prioritaskan Fase 4 butir 1 (audit log) dan butir 2 (proxy Next).
