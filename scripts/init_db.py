"""Create the database and apply schema.sql safely (no data is dropped).

Usage:
    python scripts/init_db.py

Works with local MySQL and hosted MySQL services. For a hosted service set
MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DATABASE and
MYSQL_SSL=true in the environment (or use MYSQL_URL).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402

# This script initialises the schema explicitly, so avoid a second attempt
# from the app's automatic boot initialiser.
os.environ['AUTO_INIT_DB'] = 'false'

import db  # noqa: E402
from app import create_app  # noqa: E402


def main():
    app = create_app()
    cfg = app.config
    print(f"Database target: {cfg['MYSQL_USER']}@{cfg['MYSQL_HOST']}:"
          f"{cfg['MYSQL_PORT']}/{cfg['MYSQL_DATABASE']}")
    print(f"TLS: {'enabled' if cfg.get('MYSQL_SSL') else 'disabled'}")

    try:
        with app.app_context():
            statements = db.init_database(app)
            users = db.query_one('SELECT COUNT(*) AS c FROM users')['c']
            items = db.query_one('SELECT COUNT(*) AS c FROM item_reports')['c']
    except mysql.connector.Error as exc:
        code = getattr(exc, 'errno', None)
        print('\nDatabase setup failed.', file=sys.stderr)
        print(f'MySQL error {code}: {exc}', file=sys.stderr)
        if code == 2003:
            print('Check that the host and port are correct and the MySQL '
                  'service allows connections from this machine.', file=sys.stderr)
        elif code == 1045:
            print('Check MYSQL_USER and MYSQL_PASSWORD.', file=sys.stderr)
        elif code == 1049:
            print('The database does not exist and this account cannot create '
                  'it. Create it in the hosting dashboard, then re-run.', file=sys.stderr)
        elif code in (1044, 1142):
            print('This MySQL account does not have permission to create or '
                  'change the database. Grant it access in the hosting dashboard.',
                  file=sys.stderr)
        elif 'ssl' in str(exc).lower() or 'tls' in str(exc).lower():
            print('Try MYSQL_SSL=true (hosted databases usually require TLS). '
                  'If your provider gives a CA file, set MYSQL_SSL_CA.', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'\nDatabase setup failed: {exc}', file=sys.stderr)
        return 1

    print(f'Schema applied ({statements} statements).')
    print(f'Database "{cfg["MYSQL_DATABASE"]}" is ready.')
    print(f'Existing data preserved: {users} user(s), {items} report(s).')
    if users == 0:
        print('\nNext step: create an administrator with')
        print('  python scripts/create_admin.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
