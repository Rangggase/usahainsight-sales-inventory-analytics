# UsahaInsight v1.3c — Audit Trail

Pembaruan dari **v1.3b dengan Login CSRF Fix**, untuk proyek FastAPI yang sudah berjalan di PyCharm.

## Apa yang berubah?

- Tabel `audit_events` dibuat otomatis saat startup (migrasi `CREATE TABLE IF NOT EXISTS`, aman dijalankan ulang).
- Menu **Audit Trail** di `/audit` menampilkan aktivitas administrator, waktu **UTC**, aksi, ringkasan, nilai sebelum/sesudah, filter tindakan, pencarian, dan pagination.
- Perubahan produk via formulir (tambah, edit, arsip, aktivasi), restock, penjualan manual, impor CSV produk dan penjualan mendapatkan log ketika diproses dari halaman web oleh admin yang login.
- Log dan perubahan bisnis ditulis dalam **transaksi SQLite yang sama**. Bila salah satu gagal, keduanya dibatalkan. Permintaan invoice manual yang sama tidak ditulis dua kali.
- `UPDATE/DELETE` langsung pada baris `audit_events` ditolak oleh trigger SQLite. Ini adalah perlindungan di tingkat aplikasi, bukan jaminan tidak dapat dimanipulasi oleh pihak yang punya kontrol penuh atas file database.

**Batasan:** Data historis dari sebelum v1.3c tidak diatribusikan ke admin secara retroaktif. Seed demo, proses CLI, dan login/logout belum dicatat; hanya perubahan bisnis dari web setelah upgrade yang dicatat. Impor CSV dicatat sebagai satu kejadian agregat per file, berisi jumlah dan contoh maksimal 25 SKU/invoice, **bukan** log rinci sebelum/sesudah per baris CSV. Penyimpanan satu admin ini untuk penggunaan lokal, belum untuk hosting publik.

## Instalasi di Windows / PyCharm

1. Hentikan server dengan `Ctrl+C`. **Jangan hapus** folder `instance`, `.venv`, atau `backups`.
2. Salin `UsahaInsight_v1_3c_Audit_Trail_Patch.zip` ke folder yang berisi `run.py`.
3. Backup kode dan database **saat server berhenti**:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item .\app ".\app-before-v1_3c-$stamp" -Recurse
Copy-Item .\instance\usahainsight.db ".\instance\usahainsight-before-v1_3c-$stamp.db"
```

4. Verifikasi ZIP ditemukan lalu ekstrak:

```powershell
Test-Path .\UsahaInsight_v1_3c_Audit_Trail_Patch.zip
Expand-Archive -Path .\UsahaInsight_v1_3c_Audit_Trail_Patch.zip -DestinationPath . -Force
```

5. Jalankan tes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**Target: 85 passed** (73 dari rilis 1.3b sebelumnya + 12 tes baru), jika environment dan semua file sebelumnya sesuai rilis.

6. Jalankan server, lalu login:

```powershell
$env:USAHAINSIGHT_COOKIE_SECURE='0'  # HTTP localhost saja; untuk HTTPS produksi gunakan 1
.\.venv\Scripts\python.exe run.py
```

Buka `http://127.0.0.1:8000/audit` atau menu **Audit Trail**. Login tetap memakai akun dan password administrator sebelumnya, tidak perlu di-reset.

## Pengujian manual

| ID | Tindakan | Harapan |
|---|---|---|
| TC41 | Buka `/audit` tanpa login (Incognito) | Dialihkan ke `/login` |
| TC42 | Login, tambah produk baru (mis. `AUD-2026-01`, stok awal 0) | Log `product.created`, pengguna `admin` dan nilai produk tampil |
| TC43 | Edit harga produk uji | Log `product.updated` menampilkan harga sebelum/sesudah |
| TC44 | Arsip lalu aktifkan kembali produk stok 0 | Log `product.archived` dan `product.restored` |
| TC45 | Restock produk uji sebesar 5 unit | Log `stock.restocked`, stok berubah dan jumlah benar |
| TC46 | Jual 2 unit produk uji melalui formulir | Hanya satu `sale.created`, transaksi dan stok sinkron |
| TC47 | Tolak transaksi 999 unit atau invoice ganda | Tidak ada audit `sale.created` tambahan |
| TC48 | Filter tindakan, pencarian, dan paginasi | Hasil dapat difilter; log tetap read-only |
| TC49 | Uji regresi laporan, produk, impor CSV, logout | Fitur lama tetap berjalan |

Gunakan **produk uji baru**, bukan transaksi atau data bisnis sungguhan. Setelah pengujian, produk uji bisa diarsipkan jika stoknya 0; audit tidak bisa dihapus lewat aplikasi.

## Ketika terdapat masalah

- `no such table: audit_events`: jalankan aplikasi sampai inisialisasi startup berhasil; jalankan kembali tes, pastikan `app/schema.sql` terbaru.
- `401/303 ke login`: sesi habis atau cookie belum ada; login ulang dengan domain yang konsisten (`127.0.0.1`).
- Jangan melakukan restore ke database utama demi menguji modul ini. Gunakan `verify_restore_sandbox.py` dari v1.3b bila diperlukan.
- Backup folder `app` dan `instance/usahainsight-before-v1_3c-*.db` sebelum mencoba perbaikan manual.
