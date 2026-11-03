# Hotfix Login v1.3b — cookie dan token CSRF

Pesan `Permintaan login tidak valid` merupakan kegagalan validasi CSRF yang terjadi sebelum password diperiksa. Patch ini **tidak** menonaktifkan CSRF atau login.

Yang diperbaiki:
- Cookie CSRF login menggunakan nama baru `ui_login_csrf_v2`, sehingga tidak bertabrakan dengan cookie lama yang tersimpan browser.
- Cookie CSRF login memakai `SameSite=Lax`, `HttpOnly`, serta `Secure` jika HTTPS diaktifkan. Cookie sesi autentikasi tetap `SameSite=Strict`.
- Membuka beberapa tab login tidak lagi menimpa token dari tab sebelumnya.
- Jika CSRF tidak valid, aplikasi memperlihatkan formulir login lagi serta alasan umum kegagalan, bukan halaman hitam 403.
- Pengujian keamanan tambahan memastikan token hilang/salah tetap ditolak.

## Pemasangan pada Windows/PyCharm

1. Hentikan server dengan `Ctrl+C`.
2. Simpan patch ZIP di folder yang berisi `run.py`.
3. Backup dua file kode lama (opsional jika sudah ada backup source penuh):

   ```powershell
   Copy-Item .\app\main.py .\app\main-before-loginfix.py
   Copy-Item .\app\services\auth.py .\app\services\auth-before-loginfix.py
   ```

4. Ekstrak:

   ```powershell
   Expand-Archive -Path .\UsahaInsight_v1_3b_Login_CSRF_Fix.zip -DestinationPath . -Force
   ```

5. Uji:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   ```

6. Jalankan server:

   ```powershell
   $env:USAHAINSIGHT_COOKIE_SECURE = "0"  # hanya untuk HTTP localhost
   .\.venv\Scripts\python.exe run.py
   ```

7. Buka satu alamat konsisten **http://127.0.0.1:8000/login** di Chrome Incognito, lalu login.

Jika masih ada pesan `Cookie keamanan login tidak dikirim`, periksa apakah Chrome menolak cookies untuk 127.0.0.1. Pada DevTools (F12), tab Application > Storage > Cookies > http://127.0.0.1:8000, cookie `ui_login_csrf_v2` harus muncul setelah GET /login. Jangan kirim isi cookie ke siapa pun.

Jangan campur `localhost` dan `127.0.0.1` saat pengujian. Jangan ubah konfigurasi cookie menjadi tidak aman saat aplikasi dideploy melalui internet.
