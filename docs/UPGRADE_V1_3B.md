# UsahaInsight v1.3b — Authentication & CSRF (instalasi dari v1.3a)

**Ruang lingkup:** Login administrator lokal, Argon2id, sesi server-side dengan masa berlaku 8 jam, logout/revokasi sesi, proteksi CSRF semua POST, throttling akun setelah 5 login gagal selama 15 menit. Tidak ada akun atau password bawaan. **Ini bukan otorisasi multi-tenant dan belum siap untuk hosting publik.** Backup dan restore tetap CLI-only.

## Prasyarat dan keamanan data

- Pastikan versi v1.3a sudah berhasil (59 passed + backup `VALID`).
- Jalankan `python verify_restore_sandbox.py` setelah patch dipasang untuk menguji restore tanpa mengubah database utama. Script membuat snapshot tervalidasi, mengubah salinan sementara, melakukan restore terhadap salinan itu, dan memastikan SHA-256 database aktif tetap sama. **Hentikan server** sebelum menjalankannya.
- Jangan letakkan password, berkas database, folder `backups/`, atau ZIP backup di repositori GitHub publik.
- Login melindungi halaman dan API, tetapi **jangan membuka port 8000 ke internet**. Jika kelak hosting HTTPS, atur `USAHAINSIGHT_COOKIE_SECURE=1` dan gunakan reverse proxy serta konfigurasi keamanan tambahan.

## 1 — Backup sebelum upgrade (server berhenti)

Jalankan di PowerShell PyCharm pada folder yang berisi `run.py`:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item .\instance\usahainsight.db ".\instance\usahainsight-before-v1_3b-$stamp.db" -ErrorAction Stop
Copy-Item .\app ".\app-before-v1_3b-$stamp" -Recurse -ErrorAction Stop
```

## 2 — Instal patch dan dependensi

Letakkan ZIP patch **sejajar dengan `run.py`** (jangan menggunakan full release untuk menimpa proyek aktif):

```powershell
Test-Path .\UsahaInsight_v1_3b_Auth_Security_Patch.zip
Expand-Archive -Path .\UsahaInsight_v1_3b_Auth_Security_Patch.zip -DestinationPath . -Force
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

**Target: 68 passed.** Dependensi baru: `argon2-cffi` (password tidak pernah tersimpan sebagai teks biasa). Pengujian menggunakan SQLite sementara dan tidak menimpa database utama.

## 3 — Uji restore pada sandbox (bukan database utama)

Hentikan server dan jalankan:

```powershell
.\.venv\Scripts\python.exe verify_restore_sandbox.py
```

Harus keluar dua baris `LULUS`: pemulihan sandbox sukses, **database utama tidak berubah**. Script membuat backup valid baru dan backup pre-restore dari sandbox di folder `backups/`; keduanya tetap harus dijaga privat. Script menggunakan folder sementara yang berbeda dari `instance/` supaya marker `.start_empty` milik database utama tidak berubah.

## 4 — Buat administrator pertama (CLI di komputer sendiri)

```powershell
.\.venv\Scripts\python.exe auth_manager.py init-admin --username admin
```

Masukkan password pribadi minimal 12 karakter berisi huruf dan angka. Password tidak tampil di terminal dan jangan kirim password atau screenshot password ke siapa pun. Nama pengguna tidak harus `admin`; dapat disesuaikan. **Tidak ada password default.**

> Jika sudah pernah membuat administrator, `init-admin` menolak duplikasi. Untuk mengganti password dan mencabut seluruh sesi lama:
>
> `.\.venv\Scripts\python.exe auth_manager.py set-password --username admin`

## 5 — Jalankan aplikasi dan pengujian manual

```powershell
.\.venv\Scripts\python.exe run.py
```

Buka `http://127.0.0.1:8000`: akan dialihkan ke `/login` sampai berhasil login. Periksa:

1. TC33 login dengan kredensial yang benar -> Dashboard tampil.
2. TC34 login password salah -> muncul pesan gagal tanpa akses.
3. TC35 buka `/products` dengan jendela Incognito tanpa login -> redirect `/login`; ekspor juga tidak terbuka.
4. TC36 klik **Keluar** -> sesi dicabut, halaman privat tidak bisa diakses kembali sebelum login.
5. TC39 produk, transaksi, restock, CSV import/export tetap bekerja setelah login.
6. CSRF: kirim POST tanpa token dari klien pengujian -> `403`; pengujian otomatis mencakup jalur ini.

## Penting tentang restore backup versi lama

Jika database dipulihkan dari snapshot **v1.3a** sebelum modul autentikasi ada, tabel akun mungkin belum tersedia. Jalankan kembali aplikasi untuk migrasi tabel keamanan, lalu jalankan `auth_manager.py init-admin`. Pemulihan dari backup versi baru juga dapat memulihkan sesi dan hash password pada waktu snapshot; setelah pemulihan sungguhan, sebaiknya jalankan `auth_manager.py set-password` agar sesi lama dicabut.

## Batasan v1.3b

- Login satu administrator saja, belum ada manajemen pengguna/role multiuser.
- Cookie `Secure` hanya aktif ketika `USAHAINSIGHT_COOKIE_SECURE=1`, karena mode lokal memakai HTTP. Hosting publik memerlukan HTTPS, cookie Secure, reverse proxy, konfigurasi trusted hosts, serta uji keamanan lebih lanjut.
- Belum menyediakan audit trail detail, reset password via email, atau otorisasi multi-toko.

**Tahap berikutnya: v1.3c Audit Trail** untuk perubahan produk, restock, dan transaksi, tanpa menyimpan password atau token.
