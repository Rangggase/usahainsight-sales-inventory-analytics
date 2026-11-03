"""Read-only GitHub portfolio preflight. Run: python portfolio_preflight.py
No database contents, hashes or secrets are printed. This is NOT a complete security audit.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SCREENSHOTS = [
    '01_dashboard.png', '02_products.png', '03_sales.png', '04_inventory.png',
    '05_analytics.png', '06_restock.png', '07_audit.png',
]
DOCS = [
    'docs/diagrams/erd_business.png', 'docs/diagrams/erd_security.png',
    'docs/diagrams/01_arsitektur_sistem.png',
    'docs/diagrams/02_alur_transaksi_penjualan.png',
    'docs/diagrams/03_alur_impor_csv.png',
    'docs/diagrams/04_pipeline_analitik_restock.png',
    'docs/DATABASE_DESIGN_V2.md', 'docs/SYSTEM_ARCHITECTURE_V2.md',
    'docs/BUSINESS_PROCESS_V2.md', 'docs/ANALYTICS_PIPELINE_V2.md',
]
BAD_DIR_NAMES = {'.venv', 'venv', 'instance', 'backups', 'backups_legacy', 'test-reports', '.idea'}
BAD_SUFFIXES = ('.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.pem', '.key', '.p12', '.pfx', '.zip')


def risky_file(rel: str) -> bool:
    p = Path(rel.replace('\\', '/'))
    if any(segment.lower() in BAD_DIR_NAMES or segment.lower().startswith('app-before-')
           or segment.lower().startswith('backups') for segment in p.parts[:-1]):
        return True
    lower = p.name.lower()
    return (lower.startswith('.env') or lower.endswith(BAD_SUFFIXES)
            or lower.endswith('.db-journal') or lower.startswith('readme-before-v2c'))


def git_files(*args):
    try:
        cmd = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=False)
    except OSError:
        return None
    if cmd.returncode:
        return None
    return [part.decode('utf-8', 'replace') for part in cmd.stdout.split(b'\0') if part]


def main():
    missing = []
    for path in DOCS + [f'docs/screenshots/{s}' for s in SCREENSHOTS]:
        if not (ROOT / path).is_file():
            missing.append(path)
    print('Documentation and screenshots:', 'OK' if not missing else f'{len(missing)} missing')
    for p in missing:
        print('  MISSING', p)

    tracked = git_files('ls-files', '-z')
    staged = git_files('diff', '--cached', '--name-only', '-z')
    status = 0
    if tracked is None:
        print('Git repository: not initialized / Git unavailable. Skipping tracked-file audit.')
    else:
        suspicious = sorted(set(p for p in tracked + (staged or []) if risky_file(p)))
        print('Git tracked/staged sensitive-looking paths:', len(suspicious))
        for p in suspicious:
            print('  REVIEW', p)
        if suspicious:
            status = 2

    if missing:
        status = max(status, 1)
    print('Note: this checks names and required files only; review all staged contents for secrets and privacy.')
    return status

if __name__ == '__main__':
    sys.exit(main())
