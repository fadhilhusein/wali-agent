# Audit tahap 4: verifikasi akhir

Branch `checkreview`. Diverifikasi ulang di HEAD `ffaf4f4`, setelah perbaikan putaran kedua.
Hasil putaran pertama (NO-GO di `0b3b4f5`) ada di riwayat git file ini (`5988cee`) dan diringkas di bagian akhir.

## Keputusan

| Pemakaian | Keputusan |
|---|---|
| **Demo lokal** (satu komputer, host loopback bawaan) | **GO** |
| **Di luar demo** (jaringan, `--host 0.0.0.0`, pengguna sungguhan, uang sungguhan) | **NO-GO** |

Alasan GO untuk demo lokal:

- 12 dari 13 item Critical/Required di `02-review.md` sudah diperbaiki dan dibuktikan dengan tes. Masing-masing
  ada di commit sendiri: tes ditulis lebih dulu, dipastikan gagal, lalu lulus setelah perbaikan.
- Seluruh pemeriksaan hijau: pytest 1487/1487, tes unit frontend 12/12, `tsc`, eslint, `next build`,
  `npm audit`, dan `pip-audit`.
- Perubahan perilaku yang tampak pengguna sudah disetujui pemilik sebelum dikerjakan.
- Tinjauan atas diff baru menemukan satu celah. Celah itu sudah diperbaiki di `ffaf4f4`.

Alasan NO-GO di luar demo: **#13, web tanpa login**. Atas keputusan pemilik, fitur login tidak dibuat (aturan
audit melarang fitur baru). Siapa pun yang bisa menjangkau port web bisa bertindak sebagai pemilik. Risiko ini
bisa diterima hanya selama aplikasi berjalan di loopback. Ditambah risiko sisa R-A dan R-B di bawah, aplikasi
belum siap untuk pengguna atau uang sungguhan.

## Dasar pembanding

- Tag `audit-baseline` **tidak ada** di lokal maupun di `origin`. Sebagai baseline dipakai merge-base dengan `main`,
  yaitu `38d29ea`. `main` tidak bergerak, jadi diff terhadap baseline sama dengan diff terhadap `main`:
  27 commit, 40 file, +2776/-104.

## (1) Status item Critical dan Required

| # | Status | Commit | Bukti (tes yang gagal sebelum dan lulus sesudah) |
|---|---|---|---|
| 1 | **Selesai** | `5e943e7`, `e38bfd6` | `test_a_website_that_rebinds_its_name_to_this_computer_is_refused`, `test_every_local_host_name_reaches_the_api` (termasuk `[::1]`), `local-request.test.ts`. Di server Next sungguhan, `Host: evil.example` ditolak 403. |
| 2 | **Selesai** | `775ac0f` | `next-config.test.ts`. Dicek juga lewat `next start`: `/approvals` mengirim `frame-ancestors 'none'`, `X-Frame-Options: DENY`, dan `nosniff`. |
| 3 | **Selesai** | `665041f` | `test_a_payment_that_gets_no_answer_is_not_sent_twice`, `..._whose_answer_is_lost_is_reported_as_possibly_paid`, `..._whose_outcome_cannot_be_checked_is_reported_as_uncertain`, serta dua tes entri buku yang tidak dikirim dua kali. |
| 4 | **Selesai** | `fab1ef8`, `ffaf4f4` | `test_no_further_payment_until_an_unwritten_payment_is_recorded`, `test_a_record_that_was_written_after_all_does_not_block_payments`. |
| 5 | **Selesai (rantai audit)** | `994bc3f` | `test_two_logs_on_one_file_keep_a_single_chain`, `test_processes_writing_at_the_same_time_keep_a_single_chain` (3 proses × 400 entri, stabil dalam 5 kali jalan), `test_a_damaged_audit_log_stops_start_up_with_a_plain_message`. Batas mingguan lintas proses masih terbuka (R-B). |
| 6 | **Selesai** | `bcc0d42` | `test_a_correction_that_names_two_payments_keeps_both`. |
| 7 | **Selesai** | `254670c` | `test_text_the_model_never_saw_is_unchecked_not_clean`, `test_the_part_of_a_long_text_past_the_cut_is_unchecked`. |
| 8 | **Selesai** | `fb2f825` | `test_a_suspicious_turn_cannot_change_the_books`. |
| 9 | **Selesai** | `283fa83` | `test_a_confirmation_that_meets_an_outage_can_be_tried_again` (dua titik gangguan), `test_a_confirmation_asked_again_leaves_only_the_new_request`. |
| 10 | **Selesai** | `d8e706a` | `test_cli_confirm_number_means_the_item_that_was_shown`. |
| 11 | **Selesai** | `9330488` | `decision-tone.test.ts` (3 tes). |
| 12 | **Selesai** | `2ae8516` | `test_every_early_ending_after_an_action_says_the_action_may_have_happened` (refusal, terpotong, kosong, batas langkah). |
| 13 | **Tidak dikerjakan (keputusan pemilik)** | - | Login adalah fitur baru. Risiko diterima hanya untuk demo lokal. |

Temuan lain yang ikut diperbaiki: **F1** (`5740930`, baseline offline sekarang 25 serangan dan tes menghitung dari
`attacks.yaml`), **#30/R2** (`c138ec2`, IP LAN dihapus dari `allowedDevOrigins`), dan **F8** (`next-env.d.ts`
tidak lagi termodifikasi).

## (2) Isi diff: hanya tes dan perbaikan?

**Ya.** Tidak ada fitur baru. Yang ada di luar tes:

- Perbaikan pada `guard/service.py`, `guard/audit.py`, `guard/confirm.py`, `guard/sentinel.py`, `guard/policy.py`,
  `tools/registry.py`, `agent/loop.py`, `app.py`, `interfaces/cli.py`, `interfaces/web/app.py`, dan di frontend
  `route.ts`, `next.config.ts`, `workspace-provider.tsx`, serta modul kecil `lib/local-request.ts` dan
  `lib/decision-tone.ts`.
- Kode baru yang hanya melayani perbaikan: kode alasan `RECORDS_OUT_OF_SYNC` (#4) dan `OUTCOME_UNCERTAIN` (#3),
  kategori sentinel `not_screened` (#7), `ConfirmationStore.check` dan `GuardService.token_is_live` (#9).
  Semuanya dipakai hanya oleh perbaikan masing-masing.
- Pengaturan tes: skrip `test:unit` dan `allowImportingTsExtensions`.
- `docs/baseline/offline.json` ditulis ulang. Yang berubah hanya lima serangan baru, A021 sampai A025.
- Satu commit hanya format Prettier (`2fc3bb9`).

**Perubahan perilaku yang tampak pengguna. Semuanya disetujui pemilik sebelum dikerjakan:**

| # | Sebelum | Sesudah |
|---|---|---|
| 1 | Host apa pun diterima | Hanya `127.0.0.1`, `localhost`, `[::1]`, dan nilai `--host`. IP LAN ditolak (disetujui sebagai R2). |
| 3 | Pembayaran diulang sekali saat gagal | Tidak diulang. Pesan dibedakan: "invoice still open, nothing was paid", "shows as paid, do not pay it again", atau "not certain". |
| 4 | Pembayaran yang tak tercatat diabaikan | Pembayaran berikutnya ditolak (`RECORDS_OUT_OF_SYNC`) sampai catatannya tertulis. |
| 5 | Log rusak memunculkan traceback | Pesan `SetupError` yang jelas. |
| 6 | Koreksi berisi dua pembayaran hanya menyisakan satu | Keduanya tetap ada. |
| 7 | Teks yang tak sempat disaring dianggap bersih | Dianggap belum disaring, sehingga pembayaran di giliran itu butuh pemilik. |
| 8 | Entri buku selalu jalan | Ditolak di giliran mencurigakan. |
| 9 | Permintaan hilang setelah "coba lagi" | Permintaan tetap menunggu dan bisa dikonfirmasi ulang. |
| 10 | `/confirm n` memakai daftar terkini | Memakai daftar yang terakhir ditampilkan. Kalau item sudah hilang, muncul pesan "no longer waiting". |
| 11 | Notifikasi selalu hijau | Merah untuk `denied`, `failed`, atau `needs_confirmation` saat konfirmasi. |
| 12 | Catatan "mungkin sudah dijalankan" hanya saat model tidak bisa dihubungi | Juga saat model menolak, jawaban terpotong, jawaban kosong, atau batas langkah tercapai. |

## (3) Hasil tes

Di HEAD `ffaf4f4`:

| Pemeriksaan | Hasil |
|---|---|
| `uv run pytest -q` | **1487 lulus, 0 gagal** (di `main`: 1280 lulus, 2 gagal) |
| `ruff check .` / `ruff format --check .` | bersih |
| `npm run test:unit` | 12 lulus, 0 gagal |
| `npx tsc --noEmit` (setelah `npm ci`) | bersih (3 error `lucide-react` sebelumnya hanya karena `node_modules` lokal tidak lengkap) |
| `npm run lint` | bersih |
| `npx next build` | berhasil, 6 rute |
| `next start`, lalu `curl` | header anti-framing terkirim. Proxy menolak Host `evil.example` dan IP LAN (403). |
| `npm audit --omit=dev` | 0 kerentanan |
| `uvx pip-audit` (dependensi produksi) | tidak ada kerentanan yang diketahui |

Yang **tidak** dijalankan: skrip Playwright (`test:ui`, `test:landing`, `test:workflow-demo`) karena butuh browser,
dan evaluasi dengan model sungguhan karena butuh kunci API.

## (4) Celah baru

Diff putaran kedua ditinjau ulang dengan fokus pada jalur uang, token, dan kunci file:

- **Ditemukan dan sudah diperbaiki (`ffaf4f4`).** Pada #4, catatan yang sebenarnya sudah tertulis tetapi
  dilaporkan gagal akan ditulis ulang, lalu bentrok dengan `UNIQUE(invoice_id)` selamanya. Akibatnya, semua
  pembayaran berikutnya ditolak sampai aplikasi di-restart. Tesnya terbukti gagal tanpa perbaikan.
- **Diperiksa, aman.** #9 memeriksa token dulu dan baru memakainya sesudah keputusan. Semua itu berjalan di bawah
  `RLock` guard yang sama, jadi tidak ada celah waktu untuk pemakaian ganda. Token yang dibatalkan karena
  konfirmasi ulang tidak dikembalikan ke inbox (ada tesnya). #3 tidak pernah mengirim approval yang sama dua kali.
  #7 hanya bisa menambah kecurigaan, tidak bisa menguranginya.
- **R3 dari putaran pertama tetap ada.** Pengecekan Origin tidak memeriksa port dan skema. Ini tidak bisa
  dieksploitasi dari browser karena preflight CORS gagal.

## Daftar sisa risiko

| # | Risiko | Severity | Yang perlu dilakukan |
|---|---|---|---|
| R-A | **#13: web tanpa login.** Siapa pun yang menjangkau port bertindak sebagai pemilik. | Required (diterima hanya untuk demo) | Jangan jalankan dengan `--host 0.0.0.0` atau di jaringan. Sebelum dipakai di luar demo, perlu login atau token per peluncuran (fitur baru, butuh keputusan terpisah). |
| R-B | **Batas mingguan dan inbox masih per proses.** #5 hanya membereskan rantai audit. Kalau web dan Telegram berjalan bersamaan dengan `data/` yang sama, keduanya bisa lolos cek `per_week` di waktu yang sama. Inbox konfirmasi juga tidak dibagi antarproses. | Required (lanjutan #5) | Jalankan satu antarmuka per folder `data/`, atau tambahkan lock lintas proses di sekitar keputusan dan eksekusi. |
| R-C | Pembayaran yang belum tercatat (#4) hanya disimpan di memori. Kalau aplikasi di-restart sebelum catatannya tertulis, hitungan itu hilang. | Optional | Faktur sudah berstatus `paid` di bank, jadi pembayaran ganda tetap tertahan. Yang tidak terlindungi hanya total mingguannya. |
| R-D | Pada #3, kalau faktur tampil "paid" setelah bank tidak menjawab, status yang dilaporkan `failed`, dan entri buku tidak dibuat otomatis. | Nit | Pesannya sudah tegas ("do not pay it again"). Entri buku perlu ditambah manual. |
| R-E | Jalur kunci file Windows (`msvcrt`) di #5 belum pernah diuji, karena CI dan tes berjalan di Linux. | Nit | Uji di Windows kalau aplikasi dijalankan di sana. |
| R-F | Upaya konfirmasi saat gangguan (#9) tidak dicatat di log audit. | Nit | Tambahkan event audit kalau dibutuhkan untuk penelusuran. |
| R-G | R3: port dan skema Origin tidak dicek. | Nit | Bandingkan origin lengkap (lihat #20). |
| R-H | `test:unit` belum dijalankan di CI. Action CI masih dipin dengan tag (#31). | Nit | Tambahkan langkah `npm run test:unit` di `ci.yml`, dan pin action ke SHA. |
| R-I | Item Optional/Nit #14 sampai #29 dan #32 sampai #37 belum dikerjakan. Yang paling relevan: #14 (pembayaran faktur yang tidak disebut pengguna, keputusan desain D3), #18 (jumlah tanpa batas digit), #21 (rantai audit tanpa tanda tangan), #23 (kunci guard 0644), #15 (lock global, chat tanpa rate limit). | Optional/Nit | Kerjakan sebelum dipakai di luar demo. |
| R-J | Skrip Playwright dan evaluasi dengan model sungguhan belum dijalankan. | Proses | Jalankan di mesin yang punya browser dan kunci API. |
| R-K | Tag `audit-baseline` tidak ada. | Proses | Buat tag di `38d29ea`. |

## Rollback

Belum di-merge, jadi belum ada yang perlu di-rollback. Setiap perbaikan ada di commit sendiri dan bisa di-revert
satu per satu. Tidak ada migrasi skema: `guard.db` dan `audit.jsonl` lama tetap bisa dibaca. Satu-satunya data
yang diubah adalah `docs/baseline/offline.json`, yaitu baseline tes, bukan data aplikasi.

## Ringkasan putaran pertama (`5988cee`)

NO-GO di `0b3b4f5`, karena: #3 sampai #13 belum dikerjakan; ada regresi `[::1]` (R1, diperbaiki `e38bfd6`);
penolakan IP LAN belum disetujui (R2, sekarang disetujui); dan 2 tes F1 gagal (diperbaiki `5740930`).
