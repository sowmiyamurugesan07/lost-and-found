"""Check the deployed database connection and schema.

Usage:
    python scripts/check_db.py
    python scripts/check_db.py --init

This prints the host, port, user and database name (never the password),
checks that MySQL is reachable, and lists any missing tables or columns.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402

# Do not trigger the automatic boot initialiser while diagnosing. The --init
# flag performs the schema setup deliberately.
os.environ['AUTO_INIT_DB'] = 'false'

import db  # noqa: E402
from app import create_app  # noqa: E402


def _print_target(app):
    cfg = app.config
    print('Database target:')
    print(f"  host:     {cfg['MYSQL_HOST']}:{cfg['MYSQL_PORT']}")
    print(f"  user:     {cfg['MYSQL_USER']}")
    print(f"  database: {cfg['MYSQL_DATABASE']}")
    print(f"  TLS:      {'enabled' if cfg.get('MYSQL_SSL') else 'disabled'}")
    if cfg.get('MYSQL_SSL'):
        print(f"  verify:   {bool(cfg.get('MYSQL_SSL_VERIFY'))}")
        if cfg.get('MYSQL_SSL_CA'):
            print(f"  CA file:  {cfg['MYSQL_SSL_CA']}")


def main():
    parser = argparse.ArgumentParser(description='Check Lost & Found+ database health.')
    parser.add_argument('--init', action='store_true',
                        help='apply schema.sql if tables are missing')
    args = parser.parse_args()

    app = create_app()
    _print_target(app)

    try:
        with app.app_context():
            version = db.query_one('SELECT VERSION() AS version, DATABASE() AS db')
            print(f"\nConnected to MySQL {version['version']} (database: {version['db']}).")

            if args.init:
                print('\nApplying schema.sql (CREATE ... IF NOT EXISTS only)...')
                statements = db.init_database(app)
                print(f'Schema checked ({statements} statements).')

            status = db.schema_status()
            if status['ready']:
                print('Schema: ready (all required tables and columns exist).')
                return 0

            print('Schema: INCOMPLETE')
            if status['missing_tables']:
                print('  Missing tables: ' + ', '.join(status['missing_tables']))
            for table, columns in status['missing_columns'].items():
                print(f"  Missing columns in {table}: " + ', '.join(columns))
            print('\nRun: python scripts/init_db.py')
            return 1
    except mysql.connector.Error as exc:
        code = getattr(exc, 'errno', None)
        print(f'\nConnection/schema check failed (MySQL error {code}): {exc}')
        if code == 2003:
            print('Check the host, port, firewall and whether the database service is running.')
        elif code == 1045:
            print('Check MYSQL_USER and MYSQL_PASSWORD.')
        elif code == 1049:
            print('The database does not exist. Run python scripts/init_db.py.')
        elif code in (1044, 1142):
            print('The MySQL account does not have permission for this database.')
        elif 'ssl' in str(exc).lower() or 'tls' in str(exc).lower():
            print('Try MYSQL_SSL=true; hosted databases usually require TLS.')
        return 1
    except Exception as exc:
        print(f'\nCheck failed: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
