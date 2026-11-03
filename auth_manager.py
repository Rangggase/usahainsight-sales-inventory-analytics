"""Local-only administration: python auth_manager.py init-admin."""
import argparse
import getpass
from app.database import init_db
from app.services.auth import init_admin


def main():
    parser = argparse.ArgumentParser(description='Akun administrator UsahaInsight v1.3b')
    parser.add_argument('action', choices=['init-admin', 'set-password'])
    parser.add_argument('--username', default='admin', help='Nama admin (default: admin)')
    args = parser.parse_args()
    init_db()
    first = getpass.getpass('Password (minimal 12 karakter, huruf dan angka): ')
    repeat = getpass.getpass('Ulangi password: ')
    if first != repeat:
        parser.error('Konfirmasi password tidak cocok.')
    try:
        init_admin(args.username, first, reset=args.action == 'set-password')
    except ValueError as e:
        parser.error(str(e))
    print('BERHASIL: administrator siap. Semua sesi lama dicabut jika password diperbarui.')


if __name__ == '__main__':
    main()
