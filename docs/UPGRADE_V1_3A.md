# Upgrade UsahaInsight v1.2 → v1.3a: Backup & Recovery

> **Ini tahap pertama v1.3, bukan rilis keamanan lengkap.** Login, proteksi CSRF, dan audit log belum diterapkan. Menu pada dashboard masih menampilkan versi 1.2 sampai modul keamanan selesai. Seluruh 46 pengujian v1.2 tetap dijalankan.

## Tujuan dan batasan

- `backup_manager.py backup`: membuat **snapshot SQLite konsisten** dengan SQLite Online Backup API, bahkan saat server berjalan. Tidak menggunakan `Copy-Item` langsung untuk file database aktif.
- Setiap backup menghasilkan **dua file pasangan** di `backups/`: `usahainsight-manual-...db` dan `usahainsight-manual-...json` (manifest SHA-256, ukuran, jumlah baris, metadata `.start_empty`).
- `backup_manager.py list` dan `verify`: memeriksa manifest, SHA-256, integritas database, foreign key, dan struktur tabel.
- `backup_manager.py restore FILE --confirm`: **hanya ketika server berhenti**. Membuat salinan `pre-restore` dahulu, kemudian mengganti database secara atomik. File backup awal tidak dihapus.
- Sengaja **tidak menyediakan endpoint web untuk backup/restore**, karena versi ini belum memiliki autentikasi. Backup berisi seluruh data penjualan. Folder `backups/` diabaikan Git dan **jangan diunggah ke GitHub**.

## Instalasi patch di PyCharm / Windows

Buka folder proyek `UsahaInsight` yang berisi `run.py` dan `.venv`.

1. Hentikan server (`Ctrl+C`). Gunakan path proyek aktif milikmu; **jangan** menimpa folder aplikasi lama dengan paket full release.
2. Letakkan `UsahaInsight_v1_3a_Backup_Recovery_Patch.zip` sejajar dengan `run.py`.
3. Buat backup aman offline sebelum menimpa kode:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item .\instance\usahainsight.db ".\instance\usahainsight-before-v1_3a-$stamp.db" -ErrorAction Stop
Copy-Item .\app ".\app-before-v1_3a-$stamp" -Recurse -ErrorAction Stop
```

4. Ekstrak patch, dan jalankan pengujian:

```powershell
Test-Path .\UsahaInsight_v1_3a_Backup_Recovery_Patch.zip
Expand-Archive .\UsahaInsight_v1_3a_Backup_Recovery_Patch.zip -DestinationPath . -Force
.\.venv\Scripts\python.exe -m pytest -q
```

Target rilis: **59 passed**, terdiri dari 46 tes lama dan 13 tes modul backup/recovery. Pengujian menggunakan database sementara.

## Pengujian aman tanpa mengubah database utama

### 1. Buat backup

```powershell
.\.venv\Scripts\python.exe backup_manager.py backup
```

Cari dua file `.db` dan `.json` di folder `backups/`. File backup berisi data saat pembuatan snapshot.

### 2. Tampilkan dan verifikasi

```powershell
.\.venv\Scripts\python.exe backup_manager.py list
$backup = (Get-ChildItem .\backups\usahainsight-manual-*.db | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
.\.venv\Scripts\python.exe backup_manager.py verify $backup
```

Keluaran yang diharapkan: `VALID` pada perintah `verify` dan `list`.

### 3. Uji pemulihan di database sandbox (bukan database utama)

Hentikan server dahulu, kemudian buat file database uji dari backup yang diverifikasi:

```powershell
Copy-Item $backup .\instance\restore-test.db
.\.venv\Scripts\python.exe backup_manager.py --db .\instance\restore-test.db restore $backup --confirm
```

Hasil yang diharapkan: `BERHASIL: Database dipulihkan` serta lokasi backup pengaman `pre-restore`. File `instance/usahainsight.db` tetap utuh. Hapus `instance/restore-test.db` jika pengujian selesai.

### 4. Pemulihan database utama (hanya saat diperlukan)

**PERINGATAN:** Ini mengganti seluruh data aktif dengan versi pada backup (perubahan setelah backup tidak lagi ada di database aktif). Jangan jalankan saat sekadar menguji.

```powershell
# Hentikan run.py dengan Ctrl+C, tutup proses lain yang memakai database.
.\.venv\Scripts\python.exe backup_manager.py restore $backup --confirm
```

Sebelum perubahan, sistem secara otomatis menyimpan file baru berlabel `pre-restore`. Jika proses terganggu, periksa kedua file backup sebelum menjalankan ulang. Pastikan selalu menyimpan pasangan `.db` dan `.json` di media terpisah / drive cloud privat yang aman (bukan repositori Git publik).

### Kompatibilitas

- Tidak menambah atau mengubah tabel SQLite pada database aktif.
- Tidak mengubah modul Produk, Transaksi, Stok, Impor, dan Laporan.
- `run.py`, `.venv`, `instance/usahainsight.db`, dan file CSV pengujian tidak ditimpa patch.
- Perintah `restore` menolak file tanpa manifest atau dengan hash tidak cocok.
- Pemeriksaan port 8000 membantu mencegah restore saat server standar berjalan; untuk server dengan port diubah, **tanggung jawab operator memastikan semua koneksi berhenti**.

## Tahap berikutnya

v1.3b: login/logout, hash password, perlindungan CSRF, sesi aman dan rate-limit login. Setelah itu baru pertimbangkan admin-only UI untuk backup dan histori aktivitas.
