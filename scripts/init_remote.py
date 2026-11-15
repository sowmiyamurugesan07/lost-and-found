"""Initialise a hosted MySQL database without Render Shell.

Usage (interactive):
    python scripts/init_remote.py

Usage with a local secrets file (never commit this file):
    python scripts/init_remote.py --env-file .env.render

The env file may contain either:
    MYSQL_URL=mysql://user:password@host:port/defaultdb?ssl-mode=REQUIRED
or:
    MYSQL_HOST=...
    MYSQL_PORT=...
    MYSQL_USER=...
    MYSQL_PASSWORD=...
    MYSQL_DATABASE=defaultdb
    MYSQL_SSL=true

This script applies schema.sql to the configured database. It only uses
CREATE ... IF NOT EXISTS statements and never drops data.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402


def _ask(prompt, default=None, secret=False):
    suffix = f' [{default}]' if default not in (None, '') else ''
    if secret:
        value = getpass.getpass(f'{prompt}{suffix}: ')
    else:
        value = input(f'{prompt}{suffix}: ').strip()
    return value or (default or '')


def _load_interactive():
    print('Hosted MySQL details (copy them from the Render/Aiven dashboard).')
    print('The password is not displayed or saved.\n')
    os.environ['MYSQL_HOST'] = _ask('Host')
    os.environ['MYSQL_PORT'] = _ask('Port', '3306')
    os.environ['MYSQL_USER'] = _ask('User', 'avnadmin')
    os.environ['MYSQL_PASSWORD'] = _ask('Password', secret=True)
    os.environ['MYSQL_DATABASE'] = _ask('Database', 'defaultdb')

    use_ssl = _ask('Use TLS? (Y/n)', 'y').lower() not in ('n', 'no')
    os.environ['MYSQL_SSL'] = 'true' if use_ssl else 'false'
    if use_ssl:
        verify = _ask('Verify the server certificate? (y/N)', 'n').lower() in ('y', 'yes')
        os.environ['MYSQL_SSL_VERIFY'] = 'true' if verify else 'false'
        if verify:
            os.environ['MYSQL_SSL_CA'] = _ask('CA certificate path')


def main():
    parser = argparse.ArgumentParser(
        description='Apply schema.sql to a hosted MySQL database.'
    )
    parser.add_argument('--env-file', help='Local file containing MYSQL_* values')
    parser.add_argument('--url', help='mysql:// connection URL')
    args = parser.parse_args()

    if args.url:
        os.environ['MYSQL_URL'] = args.url
    elif args.env_file:
        path = os.path.abspath(args.env_file)
        if not os.path.exists(path):
            print(f'File not found: {path}', file=sys.stderr)
            return 1
        # override=True ensures values in this file win over the local .env.
        load_dotenv(path, override=True)
    else:
        _load_interactive()

    # This script performs the initialisation deliberately.
    os.environ['AUTO_INIT_DB'] = 'false'

    from app import create_app  # noqa: E402
    import db  # noqa: E402
    import mysql.connector  # noqa: E402

    app = create_app('production')
    cfg = app.config
    print('\nDatabase target:')
    print(f"  host:     {cfg['MYSQL_HOST']}:{cfg['MYSQL_PORT']}")
    print(f"  user:     {cfg['MYSQL_USER']}")
    print(f"  database: {cfg['MYSQL_DATABASE']}")
    print(f"  TLS:      {'enabled' if cfg.get('MYSQL_SSL') else 'default negotiation'}")

    try:
        with app.app_context():
            statements = db.init_database(app)
            status = db.schema_status()
            users = db.query_one('SELECT COUNT(*) AS c FROM users')['c']
            reports = db.query_one('SELECT COUNT(*) AS c FROM item_reports')['c']
    except mysql.connector.Error as exc:
        code = getattr(exc, 'errno', None)
        print(f'\nInitialisation failed (MySQL error {code}): {exc}', file=sys.stderr)
        if code in (1044, 1045, 1049):
            print('Check the database name and user permissions.', file=sys.stderr)
        elif code in (2002, 2003, 2005, 2006, 2013):
            print('Check the host/port and the provider firewall settings.', file=sys.stderr)
        elif 'ssl' in str(exc).lower() or 'tls' in str(exc).lower():
            print('Try MYSQL_SSL=true, or MYSQL_SSL_VERIFY=false if you do '
                  'not have the provider CA certificate.', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'\nInitialisation failed: {exc}', file=sys.stderr)
        return 1

    print(f'\nSchema applied ({statements} statements).')
    print(f'Database "{cfg["MYSQL_DATABASE"]}" is ready.')
    print(f'Data preserved: {users} user(s), {reports} report(s).')
    if not status['ready']:
        print('\nWarning: schema is still incomplete.')
        if status['missing_tables']:
            print('  Missing tables: ' + ', '.join(status['missing_tables']))
        for table, columns in status['missing_columns'].items():
            print(f'  Missing columns in {table}: ' + ', '.join(columns))
        return 1

    print('\nSchema check: ready.')
    print('\nNext step: create an administrator with:')
    print('  python scripts/create_admin.py --env-file .env.render')
    print('(Use the same MYSQL_* values as this setup, or run it from the '
          'Render Shell if your plan includes one.)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
