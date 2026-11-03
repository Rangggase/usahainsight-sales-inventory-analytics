# Panduan Publikasi UsahaInsight ke GitHub (v2.0c)

**Status:** Draft portofolio, bukan instruksi untuk deployment publik aplikasi.

## 1. Pasang paket dokumentasi

Letakkan `UsahaInsight_v2c_GitHub_Portfolio.zip` sejajar dengan `run.py` pada folder proyek PyCharm.

PowerShell:

```powershell
Copy-Item .\README.md .\README-before-v2c.md
Copy-Item .\.gitignore .\.gitignore-before-v2c.txt
Expand-Archive -Path .\UsahaInsight_v2c_GitHub_Portfolio.zip -DestinationPath . -Force
```

**Penting:** File backup README di atas adalah salinan lokal, bukan untuk diunggah. Setelah selesai, pindahkan atau hapus file `README-before-v2c.md` sebelum Git stage. Periksa apakah `.gitignore` yang baru perlu digabung dengan aturan khusus dari proyekmu.

## 2. Screenshot

Tempatkan tujuh screenshot **milikmu** ke `docs/screenshots/` dengan nama:

- `01_dashboard.png`
- `02_products.png`
- `03_sales.png`
- `04_inventory.png`
- `05_analytics.png`
- `06_restock.png`
- `07_audit.png`

Screenshot harus berasal dari **data sintetis**; crop/blur informasi sensitif. File README menggunakan path tersebut. Jangan mempublikasikan capture browser yang menampilkan cookie, password atau data konsumen nyata.

## 3. Periksa README dan kode

Jalankan:

```powershell
.\.venv\Scripts\python.exe portfolio_preflight.py
.\.venv\Scripts\python.exe -m pytest -q
```

Target automated tests v1.4b sebelumnya adalah **114 passed**. Verifikasi angka nyata dari terminalmu. Untuk screenshot, preflight akan menandai file yang belum ditemukan; jangan langsung publish bila belum lengkap.

## 4. Git lokal: hindari `git add .` tanpa review

Periksa dulu apakah repository sudah ada:

```powershell
git status
```

Jika muncul `not a git repository`, mulai repository baru (hanya jika proyek ini belum punya riwayat Git):

```powershell
git init -b main
```

Periksa daftar kandidat dan file yang diabaikan:

```powershell
git status --short
git check-ignore -v .\instance\usahainsight.db
```

**Jangan stage file database aktif, backup, rahasia, ZIP patch, `.venv`, atau screenshot sensitif.** Git tidak menghapus sesuatu yang sebelumnya sudah *tracked* hanya karena ditambahkan ke `.gitignore`. Jika repository sudah punya riwayat, periksa `git ls-files` dan histori sebelum publikasi.

Tambahkan file secara eksplisit, *review* hasil staging, lalu commit:

```powershell
git add README.md .gitignore LICENSE requirements.txt requirements-dev.txt run.py run_windows.bat run_mac_linux.sh

git add app/ tests/ docs/ data/sample_products.csv data/sample_sales.csv

git add auth_manager.py backup_manager.py verify_restore_sandbox.py generate_demo_data.py reset_database.py portfolio_preflight.py

git diff --cached --name-only
git diff --cached --stat
```

Lanjut **hanya jika** daftar staged tidak mengandung file sensitif. Bila ada file tak semestinya, hentikan sebelum commit dan koreksi staging.

```powershell
git commit -m "docs: prepare UsahaInsight portfolio release"
```

## 5. Buat repository GitHub (mulai private)

Buat repo kosong bernama `usahainsight-sales-inventory-analytics` melalui GitHub. Pilih **Private**, dan **jangan** centang pembuatan README/.gitignore/LICENSE online karena ketiganya sudah ada secara lokal.

Di PyCharm terminal, gunakan URL repo yang benar-benar ditampilkan GitHub (jangan menebak URL):

```powershell
git remote -v
# Jalankan hanya jika belum ada remote origin:
git remote add origin <URL_REPOSITORY_GITHUB_ANDA>
git push -u origin main
```

Bila Git meminta login, selesaikan autentikasi lewat browser atau pengelola kredensial. Setelah file di GitHub sesuai, periksa kembali repository untuk data sensitif sebelum mengubah visibilitas menjadi Public.

## 6. Batasan penting

- `README` dan `.gitignore` tidak otomatis menghapus rahasia yang **sudah pernah masuk commit**.
- Jika ada password/token/PII yang pernah ter-commit, jangan publish dulu; lakukan rotasi dan remediasi histori.
- Periksa bahwa `docs/` hanya mengandung data contoh yang aman.
- Jangan menjanjikan demo publik di Internet sebelum konfigurasi produksi dan audit keamanan selesai.

Referensi resmi GitHub: https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
