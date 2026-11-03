# UsahaInsight v2.0b — Paket Dokumentasi Arsitektur dan Proses Bisnis

Paket ini **hanya berisi file dokumentasi**. Tidak menyertakan perubahan `app/`, database `.db`, backup, password, atau `.venv`.

## Isi

- `docs/SYSTEM_ARCHITECTURE_V2.md`: lapisan aplikasi, routes, service, penyimpanan dan batas keamanan.
- `docs/BUSINESS_PROCESS_V2.md`: proses transaksi, impor CSV, restock dan produk.
- `docs/ANALYTICS_PIPELINE_V2.md`: rumus dan perlakuan terhadap data tidak memadai.
- `docs/TRACEABILITY_ARCHITECTURE_V2.md`: hubungan dokumentasi, kode, dan pengujian.
- `docs/diagrams/01_...` s.d. `04_...`: empat diagram, masing-masing `.png`, `.svg`, dan `.dot` (editable melalui Graphviz).

## Pemasangan di PyCharm (Windows)

1. Unduh ZIP, pindahkan ke folder proyek `UsahaInsight/` yang berisi `run.py`.
2. Pastikan `Test-Path .\UsahaInsight_v2_Architecture_Documentation.zip` menghasilkan `True`.
3. Jalankan `Expand-Archive -Path .\UsahaInsight_v2_Architecture_Documentation.zip -DestinationPath . -Force`.
4. Periksa `docs/SYSTEM_ARCHITECTURE_V2.md` dan buka diagram PNG/SVG lewat panel Project.
5. Semua link relatif di Markdown tetap berfungsi jika struktur `docs/` dipertahankan.

Dokumentasi ini berdampingan dengan dokumentasi database v2.0 sebelumnya. **Jangan** menghapus `docs/DATABASE_DESIGN_V2.md` atau ERD yang telah dibuat.

## Pemeriksaan akhir sebelum GitHub

- Pastikan `PRAGMA database_list` di PyCharm benar-benar mengarah ke file SQLite utama.
- Jangan commit `instance/`, `backups/`, `.venv/`, `.env` atau file dengan rahasia.
- Screenshot untuk publikasi sebaiknya menggunakan data sintetis dan tidak menampilkan token atau data admin.
- Beri label status `local-first educational portfolio` sampai benar-benar ada hasil uji deployment publik dan uji pengguna.
