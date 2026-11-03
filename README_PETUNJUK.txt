UsahaInsight v2.0 — Paket dokumentasi database (BUKAN patch aplikasi)

DIBUAT DARI: source code v1.3b + patch login v1.3b + v1.3c + v1.4a + v1.4b.
PAKET INI TIDAK MENGUBAH DATABASE DAN TIDAK BERISI DATABASE.

PEMASANGAN:
1. Ekstrak ZIP ke folder root UsahaInsight yang berisi run.py.
2. File baru ada di docs/DATABASE_DESIGN_V2.md, docs/DB_VERIFICATION.sql,
   docs/diagrams/erd_business.png, erd_security.png, SVG, dan source DOT.
3. Buka SQL Console PyCharm Pro dan jalankan docs/DB_VERIFICATION.sql satu blok setiap kali.
4. PASTIKAN path PRAGMA database_list menunjuk instance/usahainsight.db, bukan sandbox UAT.
5. Pada v1.4b, target 9 tabel aplikasi dan 1 view (product_inventory).
   Screenshot sebelumnya menunjukkan 8 tabel; verifikasi reorder_settings.
6. Bila sesuai, simpan diagram ERD yang direview dalam README GitHub dan docs.

CATATAN: Semua instruksi SQL bersifat READ-ONLY. Jangan unggah database aktif,
password hash, token sesi atau berkas backup ke repository publik.
