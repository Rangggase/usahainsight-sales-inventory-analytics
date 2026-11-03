# Upgrade UsahaInsight v1.1 → v1.2 (Windows / PyCharm)

## Yang baru

- Halaman `/transactions/new`: invoice manual atau otomatis, tanggal penjualan, hingga 20 SKU per transaksi.
- Harga terisi dari katalog dan **dibaca ulang dari database saat penyimpanan**; harga lama tetap tersimpan dalam detail transaksi.
- Pemeriksaan stok dan larangan SKU ganda, nomor invoice ganda, tanggal masa depan, serta input tidak valid.
- Transaksi, detail barang, dan pengurangan stok ditulis bersama-sama di `BEGIN IMMEDIATE` dalam satu commit SQLite. Bila gagal, semuanya di-rollback.
- Perlindungan pengiriman ulang formulir yang sama via UUID + tabel `manual_sale_requests` agar tidak terhitung dua kali.
- Halaman `/transactions/{id}` menampilkan detail invoice, termasuk invoice impor CSV lama.
- Daftar Transaksi kini memiliki tautan ke detail invoice. Fitur v1.0 dan v1.1 tidak dihapus.

**Keamanan:** Masih aplikasi lokal single-user tanpa login, otorisasi, maupun perlindungan CSRF. Jangan diakses dari internet atau digunakan sebagai sistem kasir produksi sebelum hardening keamanan.

## Cara meng-upgrade proyek yang sudah dipakai

Lakukan ini pada folder **UsahaInsight** tempat `run.py` berada. Bukan folder induk `UsahaInsight_FastAPI_Ready`, bukan folder `app`, dan bukan folder `instance`.

1. Hentikan server FastAPI (`Ctrl+C`) dan tutup browser aplikasi.
2. Unduh `UsahaInsight_v1_2_Patch.zip`, lalu letakkan pada folder **UsahaInsight**.
3. Di Terminal **PowerShell** PyCharm, pastikan folder aktif benar: `Get-Location` dan `Test-Path .\run.py` (harus `True`).
4. **Backup database dan kode**, misalnya:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item .\instance\usahainsight.db ".\instance\usahainsight-before-v1_2-$stamp.db" -ErrorAction Stop
Copy-Item .\app ".\app-before-v1_2-$stamp" -Recurse -ErrorAction Stop
```

5. Verifikasi patch dan ekstrak ke folder proyek:

```powershell
Test-Path .\UsahaInsight_v1_2_Patch.zip
Expand-Archive -Path .\UsahaInsight_v1_2_Patch.zip -DestinationPath . -Force
```

6. Periksa seluruh pengujian otomatis menggunakan interpreter `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Hasil acuan untuk paket rilis ini: **46 passed**. Tes menggunakan database sementara, bukan database aktif.

7. Mulai server dengan interpreter yang benar:

```powershell
.\.venv\Scripts\python.exe run.py
```

8. Buka `http://127.0.0.1:8000/transactions/new`. Tabel `manual_sale_requests` ditambahkan otomatis ketika server pertama kali start. **Tabel lama tidak dihapus atau di-reset.**

> Penting: **Jangan jalankan `reset_database.py`**; script itu bukan bagian dari upgrade dan bisa menghapus data yang ingin disimpan.

## Pengujian manual (contoh)

Buat dua produk baru atau gunakan produk yang stoknya memadai. Misalnya:

| SKU | Harga jual | Stok awal |
| --- | ---: | ---: |
| UJI-SALE-01 | 15.000 | 10 |
| UJI-SALE-02 | 20.000 | 8 |

Buka **Transaksi → Buat Transaksi**, kosongkan nomor invoice agar otomatis, pilih SKU pertama 2 unit dan SKU kedua 3 unit. Klik **Simpan Transaksi**.

Hasil yang diharapkan:
- Satu invoice baru, dua baris rincian, dan total **Rp90.000**.
- Stok produk pertama turun **10 → 8** dan produk kedua **8 → 5**.
- Dashboard dan laporan CSV/Excel mencakup invoice baru (gunakan rentang tanggal yang sesuai).
- Tidak ada perubahan stok karena mengunjungi kembali URL detail invoice.

Tes negatif: buat transaksi 999 unit pada produk yang hanya punya 8 stok; aplikasi harus menampilkan pesan kesalahan dan **tidak** menyimpan invoice ataupun mengurangi stok.

Tes regresi: Impor CSV, Produk, Arsip/Restore, Restock, dan Ekspor tetap berjalan seperti semula.

## Pemulihan

Jika aplikasi bermasalah: hentikan server, dan gunakan backup kode + database yang tadi dibuat. Jangan mengembalikan database lama saat server masih berjalan.

## Struktur penambahan

```text
app/services/sales.py           layanan penjualan manual
app/templates/sale_form.html    formulir multi-SKU
app/templates/sale_detail.html  rincian invoice
app/schema.sql                 tabel idempotensi (CREATE IF NOT EXISTS)
tests/test_sales.py            tes end-to-end dan konkurensi
```
