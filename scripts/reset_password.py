"""Reset a member's password from the server.

Usage:
    python scripts/reset_password.py
    python scripts/reset_password.py --email sowmiya@college.edu

Only someone with access to the server and the database password can run this
command. The website never exposes a password-reset endpoint, so account
recovery stays a deliberate, administrator-assisted action.
"""
import argparse
import getpass
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

import db  # noqa: E402
from app import create_app  # noqa: E402

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')


def valid_password(password: str) -> bool:
    return (
        len(password) >= 8
        and re.search(r'[A-Za-z]', password) is not None
        and re.search(r'\d', password) is not None
    )


def main():
    parser = argparse.ArgumentParser(description='Reset a Lost & Found+ password.')
    parser.add_argument('--email', help='Email address of the account to update')
    args = parser.parse_args()

    email = (args.email or input('Account email: ')).strip().lower()
    if not EMAIL_RE.match(email):
        print('Please provide a valid email address.')
        return 1

    password = getpass.getpass('New password (min 8 chars, letters + numbers): ')
    confirm = getpass.getpass('Confirm new password: ')
    if password != confirm:
        print('Passwords do not match. Nothing was changed.')
        return 1
    if not valid_password(password):
        print('Password must be at least 8 characters and contain letters and numbers.')
        return 1

    app = create_app()
    with app.app_context():
        user = db.query_one('SELECT user_id, name FROM users WHERE email=%s', (email,))
        if not user:
            print(f'No account exists for {email}.')
            return 1
        db.execute(
            'UPDATE users SET password=%s WHERE user_id=%s',
            (generate_password_hash(password), user['user_id']),
        )
        print(f"Password updated for {user['name']} ({email}).")
        print('The member can now sign in with the new password.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
