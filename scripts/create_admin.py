"""Create or update the administrator account.

Usage:
    python scripts/create_admin.py
    python scripts/create_admin.py --name "Admin" --email admin@college.edu
    python scripts/create_admin.py --promote-existing

This is the ONLY supported way to create the first administrator. Registering
through the website always creates a normal `user` account.
"""
import argparse
import getpass
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')


def valid_password(password: str) -> bool:
    return len(password) >= 8 and re.search(r'[A-Za-z]', password) and re.search(r'\d', password)


def main():
    parser = argparse.ArgumentParser(description='Create a Lost & Found+ administrator.')
    parser.add_argument('--name', help='Administrator display name')
    parser.add_argument('--email', help='Administrator email')
    parser.add_argument('--password', help='Password (omit to be prompted securely)')
    parser.add_argument('--promote-existing', action='store_true',
                        help='Promote an existing account with this email to admin')
    parser.add_argument('--env-file',
                        help='Local file containing hosted MYSQL_* values (never commit it)')
    args = parser.parse_args()

    if args.env_file:
        path = os.path.abspath(args.env_file)
        if not os.path.exists(path):
            print(f'File not found: {path}')
            return 1
        load_dotenv(path, override=True)

    # Import after loading the optional hosted-database environment file.
    from app import create_app  # noqa: E402
    import db  # noqa: E402

    app = create_app()
    with app.app_context():
        if not args.name:
            args.name = input('Admin name: ').strip()
        if not args.email:
            args.email = input('Admin email: ').strip().lower()
        if not args.password:
            args.password = getpass.getpass('Admin password (min 8 chars, letters + numbers): ')
            confirm = getpass.getpass('Confirm password: ')
            if args.password != confirm:
                print('Passwords do not match. Nothing was changed.')
                return 1

        if not (2 <= len(args.name) <= 100):
            print('Please provide a valid name.')
            return 1
        if not EMAIL_RE.match(args.email):
            print('Please provide a valid email address.')
            return 1
        if not valid_password(args.password):
            print('Password must be at least 8 characters and contain letters and numbers.')
            return 1

        existing = db.query_one('SELECT user_id, role FROM users WHERE email = %s', (args.email,))
        if existing:
            if not args.promote_existing:
                print(f"An account already exists for {args.email} (role: {existing['role']}).")
                print('Re-run with --promote-existing to make it an administrator and reset its password.')
                return 1
            db.execute(
                "UPDATE users SET role='admin', password=%s, name=%s WHERE user_id=%s",
                (generate_password_hash(args.password), args.name, existing['user_id']),
            )
            print(f"Promoted existing account {args.email} to administrator.")
            return 0

        db.execute(
            """INSERT INTO users (name, email, password, role)
               VALUES (%s, %s, %s, 'admin')""",
            (args.name, args.email, generate_password_hash(args.password)),
        )
        print(f"Administrator created: {args.email}")
        print('You can now sign in at /login and open /admin.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
