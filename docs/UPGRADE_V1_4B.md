# UsahaInsight v1.4b — Smart Restock Recommendation

Paket ini adalah **patch untuk proyek v1.4a yang sudah berjalan**, bukan instalasi baru. Tidak mencakup file database, `.venv`, cookie, atau password.

## Instalasi PyCharm / Windows

1. Matikan aplikasi menggunakan `Ctrl+C` di terminal. Pastikan folder aktif adalah folder dengan `run.py`.
2. Buat backup valid, lalu backup kode aplikasi:

```powershell
.\.venv\Scripts\python.exe backup_manager.py backup
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item .\app ".\app-before-v1_4b-$stamp" -Recurse
```

3. Letakkan `UsahaInsight_v1_4b_Restock_Patch.zip` sejajar `run.py`, periksa dan ekstrak:

```powershell
Test-Path .\UsahaInsight_v1_4b_Restock_Patch.zip
Expand-Archive -Path .\UsahaInsight_v1_4b_Restock_Patch.zip -DestinationPath . -Force
.\.venv\Scripts\python.exe -m pytest -q
```

4. Jalankan:

```powershell
$env:USAHAINSIGHT_COOKIE_SECURE = '0'  # hanya pada HTTP lokal
.\.venv\Scripts\python.exe run.py
```

Akses `http://127.0.0.1:8000/restock-planner` setelah login. Tabel `reorder_settings` dibuat otomatis saat startup melalui `CREATE TABLE IF NOT EXISTS`. Tidak mengubah tabel transaksi, persediaan, atau akun.

## Cara menggunakan

1. Pada halaman **Rekomendasi Restock**, pilih periode 7/30/90 hari.
2. Klik **Atur parameter** pada produk pilihan; masukkan lead time pemasok, safety stock, dan periode tinjau.
3. Setelah tersimpan, status dan saran pembelian akan dihitung untuk produk yang sudah terdaftar setidaknya selama periode terpilih dan memiliki penjualan positif.
4. Pilih filter **Perlu pesan ulang**, lalu ekspor CSV/Excel jika perlu.
5. Perubahan parameter tercatat sebagai `reorder.settings_updated` pada halaman Audit Trail.

### Formula

- `ROP = ceil(unit terjual / jumlah hari × lead time) + safety stock`
- `Jika stok ≤ ROP: saran qty = max(1, ceil(unit terjual / jumlah hari × (lead time + periode tinjau)) + safety stock − stok tersedia); jika stok > ROP: 0`.
- Batas `Stok minimum` lama tetap digunakan oleh fitur monitoring stok, **bukan** sebagai pengganti parameter perencanaan yang belum diisi.
- Untuk produk baru, tanpa penjualan, atau tanpa konfigurasi, aplikasi **tidak membuat rekomendasi angka**; butuh pemeriksaan manual.
- ROP dan kuantitas saran **tidak** mempertimbangkan barang yang sedang dipesan, promosi, stockout historis, variasi permintaan, atau kalender pemasok. Ini rekomendasi indikatif untuk MVP lokal, bukan otomatisasi purchase order.

## Acceptance test

- TC61: konfigurasi lead 5, safety 3, review 7 untuk produk lama dengan unit terjual 60 dalam 30 hari, stok 10: ROP 13, saran pembelian 17.
- TC62: stok naik menjadi 15, konfigurasi sama: status stok cukup; saran qty 0 karena belum perlu memesan ulang.
- TC63: produk baru/zero sales: status data terbatas, ROP dan saran qty tidak tersedia.
- TC64: tanpa parameter: status atur parameter, tanpa rekomendasi angka.
- TC65: input negatif/nonangka: ditolak tanpa mengubah setting dan tanpa audit.
- TC66: ubah parameter dan periksa `reorder.settings_updated` pada Audit Trail.
- TC67: ekspor CSV/Excel sesuai filter pada halaman.
- TC68: login, logout, impor CSV, transaksi, backup, dan analytics v1.4a tetap berjalan.

**Untuk pengujian manual**, gunakan salinan database seperti pada v1.4a, jangan ubah tanggal produk/riwayat penjualan pada database operasional. Backup yang valid sebaiknya disimpan di lokasi luar folder kerja dan tidak diunggah ke GitHub.
