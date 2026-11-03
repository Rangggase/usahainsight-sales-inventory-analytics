# UsahaInsight v2.0 — Portfolio Release Checklist

Gunakan checklist ini sebagai bukti kesiapan rilis (bukan sebagai pengganti pengujian keamanan independen).

## Pemeriksaan aplikasi

- [ ] Database baseline v1.4b sudah dibackup dan hash/validitas snapshot diverifikasi.
- [ ] Server lokal bisa berjalan memakai `run.py` dan login admin hasil inisialisasi sendiri.
- [ ] Pengujian otomatis terakhir berhasil; catat versi dan hasil aktual (sebelumnya dilaporkan 114 passed).
- [ ] Skenario manual TC61–TC68 diarsipkan (dilaporkan 8/8 lulus).
- [ ] Instalasi bersih dilakukan pada database baru untuk memverifikasi README.

## Dokumentasi

- [ ] `docs/DATABASE_DESIGN_V2.md` cocok dengan SQLite yang terhubung di PyCharm (9 tabel aplikasi + view inventory).
- [ ] Diagram bisnis, security, architecture, sales, import CSV, analytics tersedia dan dapat dibuka.
- [ ] Screenshot `01_dashboard.png` s.d. `07_audit.png` benar-benar ada.
- [ ] Tidak ada screenshot yang memuat password, cookie, data pelanggan atau informasi sensitif.
- [ ] README, panduan instalasi, metodologi dan batasan saling konsisten.

## GitHub

- [ ] File `.gitignore` sudah diperiksa dan mencakup file sensitif lokal.
- [ ] `git diff --cached --name-only` telah direview sebelum commit.
- [ ] `git ls-files` tidak mencakup `.db`, backup, `.env`, dan arsip patch.
- [ ] Repository dibuat Private dahulu.
- [ ] Setelah audit, tentukan apakah repository layak diubah menjadi Public.

## Validasi penggunaan

- [ ] Calon pengguna UMKM menjalankan tugas produk, penjualan, stok dan laporan dengan data demo.
- [ ] Catat waktu dan kesulitan penggunaan, lalu rangkum umpan balik yang diizinkan.
- [ ] Catat keterbatasan: lokal, single admin, data sintetis, rekomendasi deterministik.
- [ ] Rekam video demonstrasi 3–5 menit menggunakan data sintetis.
- [ ] Tag rilis hanya setelah semua pekerjaan yang wajib selesai.

**Status saat ini:** Dokumen disiapkan; checklist di atas belum dianggap selesai hanya karena berkas tersedia.
