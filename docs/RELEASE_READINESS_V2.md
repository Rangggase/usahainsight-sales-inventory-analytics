# UsahaInsight v2.0 — Final Release Readiness

**Status:** release candidate; belum dipublikasikan.

## Bukti keberhasilan (hasil pengujian yang dilaporkan)
- 114 pengujian otomatis lulus pada hasil clone GitHub dengan environment baru.
- RC01–RC07 clean installation: 7/7 lulus.
- TC61–TC68 pengujian restock: 8/8 lulus.
- `portfolio_preflight.py`: dokumentasi dan screenshot OK; 0 path sensitif terdeteksi berdasarkan nama.
- `git status -sb`: `main...origin/main` (saat laporan).

Lulusnya pengujian tidak membuktikan keamanan produksi atau tidak adanya bug.

## Checklist sebelum GitHub Release
- [ ] `git status -sb` bersih dan sinkron.
- [ ] Audit **isi dan seluruh histori Git**, bukan hanya nama file.
- [ ] CSV demo, screenshot, dan metadata tidak berisi data pribadi/rahasia.
- [ ] Database aktif, backup, `.env`, `.venv`, dan kredensial tidak termasuk commit.
- [ ] Pemeriksaan dependency dilakukan dan temuannya ditindaklanjuti.
- [ ] README, semua screenshot, ERD, dan diagram dapat dibuka di GitHub.
- [ ] Hasil clean installation disimpan sebagai bukti.
- [ ] Uji pengguna UMKM telah dilakukan dengan izin dan hasilnya tercatat.
- [ ] Video demo 3–5 menit sudah dibuat menggunakan data sintetis.
- [ ] Versi internal aplikasi dan tag portofolio dijelaskan secara konsisten.
- [ ] Release notes lengkap, keterbatasan disebutkan dengan jelas.
- [ ] GitHub Release disiapkan sebagai draft sebelum dipublikasikan.
- [ ] Repo diubah menjadi Public hanya setelah audit aman dan diputuskan oleh pemilik.

Lanjutkan dengan `docs/SECURITY_REVIEW_V2.md`, `docs/UAT_UMKM_V2.md`, dan `docs/DEMO_SCRIPT_FINAL_V2.md`.
