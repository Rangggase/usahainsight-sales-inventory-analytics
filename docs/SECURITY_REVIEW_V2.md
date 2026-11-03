# Panduan Audit Repository dan Git History

Jalankan dari root repository di PowerShell. Perintah ini bersifat baca-saja dan tidak mengubah Git.

```powershell
git status -sb
git ls-files
git log --all --format= --name-only | Sort-Object -Unique
git log --all --format= --name-only | Sort-Object -Unique | Select-String -Pattern '(?i)(\.env($|\.)|\.db($|-)|\.sqlite|(^|/)(instance|backups?|\.venv)/|\.pem$|\.p12$|id_rsa|credentials|secret)'
git grep -n -I -i -E 'password|secret|token|api[_-]?key|private[_-]?key|authorization' -- ':!*.svg' ':!*.png'
```

Pencarian kata `password` pada kode tes bukan berarti kebocoran. Audit secara manual isi setiap temuan. Periksa juga data nyata di screenshot/CSV dan file berbahaya yang mungkin dinamai tidak mencurigakan.

Bila menemukan credential yang sudah pernah di-commit, **cabut/rotasi credential segera**, pertahankan repo tetap Private, dan rencanakan pemulihan riwayat secara hati-hati. Jangan force-push tanpa evaluasi dampaknya. Lihat panduan resmi: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository

Opsional pemeriksaan dependensi di virtual environment proyek:

```powershell
.\.venv\Scripts\python.exe -m pip install pip-audit
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt
```

Jika ada peringatan, evaluasi peringatan dan uji kembali sebelum mengubah dependency. Jangan menganggap skrip ini sebagai audit penetrasi atau audit privasi yang lengkap.
