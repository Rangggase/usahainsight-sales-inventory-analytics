# UsahaInsight v1.4a — Sales Velocity & Slow-Moving Product Analysis

## Ringkasan

v1.4a menambahkan halaman **Analitik Persediaan** di `/insights` dan ekspor `/insights/export` (CSV atau Excel). Seluruh halaman dan ekspor tetap memerlukan login. Fitur ini bersifat **deskriptif**, bukan prediksi AI atau rekomendasi pembelian.

Paket patch ini ditujukan untuk **UsahaInsight v1.3c yang sudah memasang Login CSRF Fix**. Jangan dipasang ke v1.0/v1.1.

## Upgrade Windows / PyCharm

1. Hentikan server (`Ctrl+C`). Pastikan PyCharm bekerja di folder yang berisi `run.py` dan `.venv`.
2. Buat backup database **dan source code**, serta simpan backup ke lokasi yang berbeda dari folder proyek bila memungkinkan.
3. Unduh `UsahaInsight_v1_4a_Analytics_Patch.zip` dan letakkan sejajar dengan `run.py`.
4. Buka Terminal PyCharm (PowerShell) dan jalankan:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv\Scripts\python.exe backup_manager.py backup
Copy-Item .\app ".\app-before-v1_4a-$stamp" -Recurse
Test-Path .\UsahaInsight_v1_4a_Analytics_Patch.zip
Expand-Archive -Path .\UsahaInsight_v1_4a_Analytics_Patch.zip -DestinationPath . -Force
.\.venv\Scripts\python.exe -m pytest -q
$env:USAHAINSIGHT_COOKIE_SECURE="0"
.\.venv\Scripts\python.exe run.py
```

`Test-Path` harus memberikan `True` sebelum mengekstrak. Target pengujian: **93 passed**. Jika terjadi kegagalan tes, jangan lanjut memasukkan data; kirim output error terlebih dahulu.

5. Buka `http://127.0.0.1:8000/login`, login menggunakan akun admin yang sudah dibuat, lalu klik **Analitik Persediaan**.

## Definisi dan asumsi perhitungan

- Periode: kalender **7, 30, atau 90 hari termasuk hari ini**, berdasarkan tanggal lokal komputer server.
- Hanya produk **aktif** yang masuk ke daftar; transaksi historis penjualan tetap dihitung per produk aktif. Penjualan bertanggal masa depan **dikecualikan**.
- **Unit terjual** = jumlah unit dari baris transaksi (`transaction_items`) dalam jendela tanggal, tidak menghitung restock.
- **Rata-rata unit/hari** = unit terjual / jumlah hari kalender periode (bukan hari yang memiliki penjualan).
- **Estimasi cakupan stok** = stok saat ini / rata-rata unit/hari; jika penjualan 0 atau stok 0, ditampilkan `Tidak dapat dihitung`. Jangan ditafsirkan sebagai tak hingga atau kepastian stok.
- **Lambat terjual** = produk aktif dengan stok > 0, penjualan <= 2 unit selama jendela, dan produk sudah terdaftar setidaknya selama jendela. Ini aturan sederhana untuk MVP, bukan kategori universal.
- **Produk baru** = tanggal pendaftaran pada database berumur kurang dari panjang periode. Tanggal dibuat di SQLite bisa lebih baru daripada tanggal pertama berjualan di dunia nyata, khususnya setelah impor histori. Maka status baru bisa merefleksikan onboarding data, bukan produk baru sesungguhnya.
- **Tanpa penjualan** = 0 unit dalam jendela; dapat mencakup produk baru dan stok kosong.
- Tidak menggunakan data HPP, histori pengadaan, lead time, musiman, atau profit untuk perhitungan ini. Tidak cocok untuk mengukur inventory turnover **berbasis nilai**.
- Dashboard/demo adalah data sintetis kecuali database sendiri dibuat dan diisi.

## Manual Acceptance Testing v1.4a

- **TC51**: Ubah periode 7 → 30 → 90; jumlah unit produk sesuai transaksi berperiode.
- **TC52**: Produk usia 90+ hari dengan stok positif, terjual 0–2 unit selama 30 hari, berlabel `Lambat terjual`.
- **TC53**: Produk baru yang belum terjual diberi label `Produk baru`, bukan `Lambat terjual`.
- **TC54**: Kecepatan = jumlah unit / jumlah hari periode.
- **TC55**: Cakupan stok = stok / kecepatan bila kecepatan positif.
- **TC56**: Jika penjualan 0, sistem menampilkan `Tidak dapat dihitung` tanpa crash.
- **TC57**: Filter SKU, kategori, dan status menghasilkan himpunan yang tepat.
- **TC58**: Unduhan CSV dan Excel sesuai filter yang aktif; Excel berisi `Ringkasan` dan `Analisis Produk`.
- **TC59**: Login, backup/restore sandbox, produk, stok, transaksi, audit, dan laporan tetap berjalan.

## Catatan keamanan dan data

- Patch **tidak mengandung file database, backup, password, maupun folder `.venv`**.
- Ekspor CSV dan Excel menyaring teks yang menyerupai formula spreadsheet.
- Halaman dan unduhan mengikuti middleware autentikasi v1.3b/v1.3c. Hanya gunakan server HTTP untuk pengujian lokal, bukan deployment publik.
