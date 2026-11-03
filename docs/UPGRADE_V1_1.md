# UsahaInsight v1.1 — Upgrade & Pengujian

## Yang berubah

- Menu **Produk**: katalog aktif/arsip, pencarian produk, tambah produk lewat formulir web.
- Edit nama, kategori, harga jual, dan batas minimum stok. SKU tetap permanen.
- Arsip (soft delete), hanya untuk produk dengan **stok 0**, dan aktifkan kembali.
- `products.is_active` ditambahkan melalui migrasi SQLite otomatis saat server pertama kali menyala setelah upgrade.
- Impor CSV dan restock menolak produk yang diarsipkan.
- Semua invoice dan `stock_movements` lama dipertahankan. Harga jual yang sudah tersimpan pada `transaction_items` tidak berubah ketika harga katalog diedit.
- `tests/test_products.py` melengkapi 8 test sebelumnya menjadi **22 tes**.

## Cara upgrade pada proyek yang SUDAH berjalan (Windows / PyCharm)

Jalankan perintah berikut di Terminal PyCharm, dari **folder utama `UsahaInsight`** tempat `run.py` dan `.venv` berada.

**1. Matikan server** dengan Ctrl+C. Jangan jalankan upgrade saat server berjalan.

**2. Backup database dan source code:**

```powershell
Copy-Item .\instance\usahainsight.db .\instance\usahainsight-before-v1_1.db
Copy-Item .\app .\app-before-v1_1 -Recurse
```

**3. Pindahkan file `UsahaInsight_v1_1_Patch.zip` ke folder utama proyek**, lalu jalankan:

```powershell
Expand-Archive -Path .\UsahaInsight_v1_1_Patch.zip -DestinationPath . -Force
```

Perintah ini hanya mengganti source code yang dibutuhkan; **tidak ada file `instance/usahainsight.db` atau `.venv` dalam ZIP**.

**4. Tes dan jalankan**:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe run.py
```

Target pengujian adalah `22 passed`. Saat startup, kolom `is_active` ditambahkan otomatis tanpa mereset transaksi dan produk lama.

**5.** Buka http://127.0.0.1:8000/products untuk melihat menu baru.

## Skenario penerimaan v1.1

1. Tambah produk: `UJI-CRUD-001`, nama `Produk CRUD`, kategori `Uji`, harga `12000`, batas minimum `3`, stok awal `10` → berhasil tersimpan, stok 10.
2. Tambah lagi SKU sama → ditolak, tanpa menambah stok.
3. Edit produk menjadi harga `15000`, nama `Produk CRUD Diedit` → harga katalog berubah, stok tetap 10, histori invoice lama tidak berubah.
4. Coba Arsipkan pada stok 10 → ditolak (stok harus 0).
5. Tambah produk kedua dengan stok awal `0` → arsipkan → hilang dari katalog aktif, muncul di tab Diarsipkan → Aktifkan → kembali ke katalog aktif.
6. Jalankan `pytest -q` → seluruh pengujian berhasil.

## Batasan MVP lokal

Belum ada login, perlindungan CSRF, otorisasi per pengguna, dan transaksi manual melalui UI. Jalankan **hanya pada localhost**, bukan sebagai layanan publik. Transaksi penjualan masih melalui impor CSV dan akan dikembangkan pada fase berikutnya.

## Jika ada masalah

- Jika `pytest` gagal, gunakan informasi error pada terminal dan laporkan sebelum menjalankan aplikasi dengan data asli.
- Jika perlu kembali ke kode lama: berhentikan server lalu salin isi `app-before-v1_1` ke `app` lagi.
- **Jangan menghapus database saat rollback.** Migrasi `is_active` menambah kolom dan tidak menghapus informasi lama. Kode v1.0 secara umum akan mengabaikan kolom tambahan tersebut, tetapi jika kamu ingin rollback menyeluruh gunakan backup database `usahainsight-before-v1_1.db` (perubahan data yang dilakukan setelah backup akan hilang).
