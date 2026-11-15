"""Shared pytest fixtures.

The integration tests use a REAL MySQL database named
`lost_and_found_plus_test` (override with TEST_MYSQL_DATABASE). The test
database is created if missing and its tables are cleared before each test.
The production database is never touched.
"""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector
from werkzeug.security import generate_password_hash

import db
from app import create_app

TEST_DATABASE = os.environ.get('TEST_MYSQL_DATABASE', 'lost_and_found_plus_test')
TABLES = ('notifications', 'matches', 'claims', 'item_reports', 'users')


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    application = create_app('development')
    application.config.update(
        TESTING=True,
        CSRF_ENABLED=False,
        SECRET_KEY='test-secret',
        MYSQL_DATABASE=TEST_DATABASE,
        UPLOAD_FOLDER=str(tmp_path_factory.mktemp('uploads')),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    with application.app_context():
        try:
            db.init_database(application)
        except mysql.connector.Error as exc:
            pytest.skip(f'MySQL is not available for integration tests: {exc}')
    return application


@pytest.fixture(autouse=True)
def clean_database(request):
    """Clear tables before each test — but only when the test uses the app.

    Pure algorithm tests (test_matching.py) therefore run without MySQL.
    """
    if 'app' not in request.fixturenames:
        yield
        return
    application = request.getfixturevalue('app')
    with application.app_context():
        for table in TABLES:
            db.execute(f'DELETE FROM {table}')
    yield


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def register(client, name='Sowmiya M', email='sowmiya@college.edu',
             password='Password123', **extra):
    payload = {
        'name': name, 'email': email, 'password': password,
        'confirm_password': password,
    }
    payload.update(extra)
    return client.post('/register', data=payload, follow_redirects=False)


def login(client, email='sowmiya@college.edu', password='Password123'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=False)


def logout(client):
    return client.post('/logout', follow_redirects=False)


def make_user(app, name='Arun Kumar', email='arun@college.edu',
              password='Password123', role='user'):
    with app.app_context():
        return db.execute(
            """INSERT INTO users (name, email, password, role)
               VALUES (%s, %s, %s, %s)""",
            (name, email, generate_password_hash(password), role),
        )


def create_item(app, user_id, item_type='Lost', name='Black wallet',
                category='Accessories', description='Black leather wallet with an ID card inside',
                color='Black', brand='Fossil', location='Block B',
                marks='Small scratch on the corner', item_date=None, status='Active',
                is_returned=0, image=None):
    with app.app_context():
        return db.execute(
            """INSERT INTO item_reports
                   (user_id, item_name, category, item_type, description, color,
                    brand, location, distinctive_marks, item_date, image, status, is_returned)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (user_id, name, category, item_type, description, color, brand,
             location, marks, item_date or date.today(), image, status, is_returned),
        )


def recalc(app, item_id):
    from services import match_service
    with app.app_context():
        return match_service.recalculate_for_item(item_id)


@pytest.fixture()
def tomorrow():
    return date.today() + timedelta(days=1)
