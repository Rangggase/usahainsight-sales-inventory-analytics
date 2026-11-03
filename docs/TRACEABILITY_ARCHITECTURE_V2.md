# Matriks Ketertelusuran — Diagram ↔ Source Code ↔ Pengujian

Dokumen ini membantu pembaca portofolio memverifikasi bahwa gambar tidak menampilkan arsitektur hipotetis.

| Klaim dalam diagram | Sumber implementasi | Bukti pengujian / penerimaan |
|---|---|---|
| Login, sesi, CSRF dan halaman terlindungi | `app/main.py`, `app/services/auth.py` | `tests/test_auth.py`, `test_login_cookie_fix.py`, TC33–TC38 |
| CRUD produk, arsip/aktivasi | `app/services/products.py` | `tests/test_products.py`, TC11–TC15 |
| Transaksi multi-produk atomik dan idempotensi | `app/services/sales.py` | `tests/test_sales.py`, TC21–TC26 |
| Impor produk/penjualan serta restock | `app/services/importers.py` | `tests/test_app.py`, TC01–TC05 |
| Ledger stok dan view agregasi | `app/schema.sql` | `tests/test_app.py`, TC22, TC54–TC56 |
| Audit per aksi bisnis terautentikasi | `app/services/audit.py` + pemanggil service | `tests/test_audit.py`, TC41–TC49 |
| Dashboard dan laporan | `app/services/analytics.py`, `reports.py` | `tests/test_app.py`, TC25, TC58 |
| Klasifikasi dan velocity/coverage | `inventory_intelligence.py` | `tests/test_insights.py`, TC51–TC59 |
| ROP, safety stock, status dan ekspor | `restock_planner.py` | `tests/test_restock_planner.py`, TC61–TC68 |
| Backup dan restore melalui terminal | `app/services/backups.py`, `backup_manager.py` | `tests/test_backups.py` dan verifikasi sandbox |
| 9 tabel aplikasi + 1 view | `app/schema.sql`, `app/services/auth.py`, `app/database.py` | SQL Console PyCharm + `PRAGMA database_list` |

**Perlu verifikasi sebelum publikasi:** jalankan ulang pengujian pada baseline v1.4b di komputer proyek dan simpan hasilnya; jangan menggunakan tangkapan layar database atau log yang memuat data sensitif pengguna.
