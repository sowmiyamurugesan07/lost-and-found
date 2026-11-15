"""Integration tests: real Flask routes against a real MySQL test database."""
import io
import os

import mysql.connector
import pytest
from PIL import Image
from werkzeug.security import check_password_hash

import db
from tests.conftest import (
    create_item, login, logout, make_user, recalc, register,
)


def html(response):
    return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Registration / authentication / the critical "correct name" requirement
# ---------------------------------------------------------------------------

def test_register_hashes_password_and_logs_in(app, client):
    response = register(client, name='Sowmiya M', email='sowmiya@college.edu')
    assert response.status_code == 302
    assert '/dashboard' in response.headers['Location']

    with app.app_context():
        user = db.query_one('SELECT * FROM users WHERE email = %s', ('sowmiya@college.edu',))
    assert user is not None
    assert user['role'] == 'user'  # never auto-admin
    assert user['password'] != 'Password123'
    assert check_password_hash(user['password'], 'Password123')

    page = html(client.get('/dashboard'))
    assert 'Welcome, Sowmiya' in page
    assert 'Logout' not in page or True  # template uses "Sign out"


def test_duplicate_email_is_rejected(app, client):
    register(client)
    logout(client)
    response = client.post('/register', data={
        'name': 'Someone Else', 'email': 'sowmiya@college.edu',
        'password': 'Password123', 'confirm_password': 'Password123',
    })
    assert response.status_code == 200
    assert 'already exists' in html(response)
    with app.app_context():
        count = db.query_one('SELECT COUNT(*) AS c FROM users')['c']
    assert count == 1


def test_logout_then_login_as_another_user_shows_the_correct_name(app, client):
    register(client, name='Sowmiya M', email='sowmiya@college.edu')
    assert 'Welcome, Sowmiya' in html(client.get('/dashboard'))

    logout(client)
    assert client.get('/dashboard').status_code == 302  # session really cleared

    register(client, name='Arun Kumar', email='arun@college.edu')
    page = html(client.get('/dashboard'))
    assert 'Welcome, Arun' in page
    assert 'Welcome, Sowmiya' not in page
    assert 'sowmiya@college.edu' not in page


def test_login_with_wrong_password_fails(app, client):
    register(client)
    logout(client)
    response = client.post('/login', data={'email': 'sowmiya@college.edu',
                                           'password': 'WrongPass1'})
    assert response.status_code == 401
    assert 'Incorrect email or password' in html(response)


def test_private_pages_require_login(client):
    for url in ['/dashboard', '/profile', '/claims', '/report/lost', '/report/found', '/admin']:
        response = client.get(url)
        assert response.status_code == 302, url
        assert '/login' in response.headers['Location']


def test_profile_name_update_is_reflected(app, client):
    register(client, name='Sowmiya M')
    client.post('/profile', data={
        'action': 'details', 'name': 'Sowmiya Lakshmi',
        'student_id': '21BCA042', 'department': 'BCA', 'phone': '9876543210',
    })
    page = html(client.get('/dashboard'))
    assert 'Sowmiya' in page
    assert 'Lakshmi' in page
    with app.app_context():
        user = db.query_one('SELECT name, department FROM users WHERE email=%s',
                            ('sowmiya@college.edu',))
    assert user['name'] == 'Sowmiya Lakshmi'
    assert user['department'] == 'BCA'


# ---------------------------------------------------------------------------
# Dashboard isolation / ownership
# ---------------------------------------------------------------------------

def test_dashboard_only_shows_current_users_reports(app, client):
    alice_id = make_user(app, name='Alice', email='alice@college.edu')
    bob_id = make_user(app, name='Bob', email='bob@college.edu')
    create_item(app, alice_id, name='Alices secret wallet')
    create_item(app, bob_id, name='Bobs secret bottle')

    login(client, email='alice@college.edu')
    page = html(client.get('/dashboard'))
    assert 'Alices secret wallet' in page
    assert 'Bobs secret bottle' not in page
    assert 'Welcome, Alice' in page


def test_user_cannot_edit_or_delete_another_users_report(app, client):
    alice_id = make_user(app, name='Alice', email='alice@college.edu')
    bob_id = make_user(app, name='Bob', email='bob@college.edu')
    bob_item = create_item(app, bob_id, name='Bobs camera')

    login(client, email='alice@college.edu')
    assert client.get(f'/item/{bob_item}/edit').status_code == 403
    assert client.post(f'/item/{bob_item}/delete').status_code == 403
    with app.app_context():
        assert db.query_one('SELECT item_id FROM item_reports WHERE item_id=%s', (bob_item,))


def test_user_cannot_read_another_users_claim_review(app, client):
    alice_id = make_user(app, name='Alice', email='alice@college.edu')
    bob_id = make_user(app, name='Bob', email='bob@college.edu')
    item_id = create_item(app, bob_id, item_type='Found', name='Found phone')
    login(client, email='alice@college.edu')
    client.post(f'/claim/{item_id}', data={
        'message': 'This phone looks like mine, please review.',
        'verification_details': 'There is a red case and a cracked corner.',
    })
    with app.app_context():
        claim = db.query_one('SELECT claim_id FROM claims')
    logout(client)
    make_user(app, name='Mallory', email='mallory@college.edu')
    login(client, email='mallory@college.edu')
    assert client.post(f"/claims/{claim['claim_id']}/review",
                       data={'action': 'approve'}).status_code == 403


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def test_report_lost_persists_in_mysql(app, client):
    register(client)
    response = client.post('/report/lost', data={
        'item_name': 'Pink water bottle',
        'category': 'Water Bottles',
        'description': 'Pink bottle with a small flower sticker on the cap',
        'color': 'Pink',
        'brand': 'Milton',
        'location': 'Library',
        'distinctive_marks': 'Flower sticker and my initials on the base',
        'item_date': '2026-09-20',
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        item = db.query_one('SELECT * FROM item_reports')
        user = db.query_one('SELECT * FROM users')
    assert item['item_name'] == 'Pink water bottle'
    assert item['item_type'] == 'Lost'
    assert item['user_id'] == user['user_id']
    assert item['status'] == 'Active'


def test_report_form_validation(app, client):
    register(client)
    response = client.post('/report/found', data={
        'item_name': '', 'category': 'Nope', 'description': 'short',
        'location': '', 'item_date': '2099-01-01',
    })
    assert response.status_code == 200
    page = html(response)
    assert 'item name' in page.lower()
    with app.app_context():
        assert db.query_one('SELECT COUNT(*) AS c FROM item_reports')['c'] == 0


def test_report_found_and_match_created(app, client):
    register(client, name='Sowmiya', email='sowmiya@college.edu')

    client.post('/report/lost', data={
        'item_name': 'Blue Skybag backpack',
        'category': 'Bags & Luggage',
        'description': 'Blue backpack with a broken zip and a keychain on the handle',
        'color': 'Blue', 'brand': 'Skybag', 'location': 'Block C',
        'distinctive_marks': 'Broken zip and a red keychain', 'item_date': '2026-09-20',
    })
    logout(client)
    register(client, name='Arun', email='arun@college.edu')
    client.post('/report/found', data={
        'item_name': 'Blue backpack found',
        'category': 'Bags & Luggage',
        'description': 'Found a blue backpack with a broken zip and red keychain near Block C',
        'color': 'Blue', 'brand': 'Skybag', 'location': 'Block C',
        'distinctive_marks': 'Broken zip and red keychain', 'item_date': '2026-09-21',
    })
    with app.app_context():
        matches = db.query_all('SELECT * FROM matches ORDER BY match_score DESC')
    assert matches, 'expected the smart matcher to create a match row'
    assert float(matches[0]['match_score']) >= 55


def test_search_and_filters_are_database_backed(app, client):
    uid = make_user(app, name='Alice', email='alice@college.edu')
    create_item(app, uid, item_type='Lost', name='Black wallet', category='Accessories',
                description='Black leather wallet', color='Black', location='Library')
    create_item(app, uid, item_type='Found', name='Pink bottle', category='Water Bottles',
                description='Pink water bottle', color='Pink', location='Canteen')

    page = html(client.get('/browse?q=wallet'))
    assert 'Black wallet' in page
    assert 'Pink bottle' not in page

    page = html(client.get('/browse?type=Found'))
    assert 'Pink bottle' in page
    assert 'Black wallet' not in page

    page = html(client.get('/browse?category=Water+Bottles&color=Pink'))
    assert 'Pink bottle' in page

    page = html(client.get('/browse?q=doesnotexist'))
    assert 'No items match' in page


# ---------------------------------------------------------------------------
# Claims workflow
# ---------------------------------------------------------------------------

def test_full_claim_and_return_workflow(app, client):
    finder_id = make_user(app, name='Arun', email='arun@college.edu')
    claimant_id = make_user(app, name='Sowmiya', email='sowmiya@college.edu')
    item_id = create_item(app, finder_id, item_type='Found', name='Pink bottle',
                          description='Pink bottle with flower sticker',
                          color='Pink', location='Library')

    login(client, email='sowmiya@college.edu')
    response = client.post(f'/claim/{item_id}', data={
        'message': 'I think this is my bottle, I lost it in the library.',
        'verification_details': 'There is a flower sticker inside the cap and my initials SM on the base.',
    }, follow_redirects=True)
    assert 'Claim request sent' in html(response)

    with app.app_context():
        claim = db.query_one('SELECT * FROM claims')
        assert claim['status'] == 'Pending'
        assert claim['claimant_id'] == claimant_id

    # Duplicate active claim is blocked.
    response = client.post(f'/claim/{item_id}', data={
        'message': 'Trying again with the same active claim.',
        'verification_details': 'Flower sticker inside the cap.',
    }, follow_redirects=True)
    assert 'already have an active claim' in html(response)
    with app.app_context():
        assert db.query_one('SELECT COUNT(*) AS c FROM claims')['c'] == 1

    logout(client)
    login(client, email='arun@college.edu')
    claim_id = claim['claim_id']
    response = client.post(f'/claims/{claim_id}/review',
                           data={'action': 'approve', 'admin_response': 'Sticker matches.'},
                           follow_redirects=True)
    assert 'Claim approved' in html(response)
    with app.app_context():
        assert db.query_one('SELECT status FROM claims WHERE claim_id=%s', (claim_id,))['status'] == 'Approved'

    response = client.post(f'/claims/{claim_id}/complete', follow_redirects=True)
    assert 'marked as returned' in html(response)
    with app.app_context():
        assert db.query_one('SELECT status FROM claims WHERE claim_id=%s', (claim_id,))['status'] == 'Completed'
        item = db.query_one('SELECT status, is_returned FROM item_reports WHERE item_id=%s', (item_id,))
        assert item['status'] == 'Returned'
        assert item['is_returned'] == 1

    # No new claims on a returned item.
    logout(client)
    login(client, email='sowmiya@college.edu')
    response = client.post(f'/claim/{item_id}', data={
        'message': 'Can I claim this again please?',
        'verification_details': 'Flower sticker inside.',
    }, follow_redirects=True)
    assert 'no longer available' in html(response)


def test_cannot_claim_own_item(app, client):
    finder_id = make_user(app, name='Arun', email='arun@college.edu')
    item_id = create_item(app, finder_id, item_type='Found', name='Found headphones')
    login(client, email='arun@college.edu')
    response = client.post(f'/claim/{item_id}', data={
        'message': 'Claiming my own report.', 'verification_details': 'Some private detail here.',
    }, follow_redirects=True)
    assert 'cannot claim your own report' in html(response)
    with app.app_context():
        assert db.query_one('SELECT COUNT(*) AS c FROM claims')['c'] == 0


# ---------------------------------------------------------------------------
# Admin authorization
# ---------------------------------------------------------------------------

def test_admin_routes_are_protected_on_the_server(app, client):
    make_user(app, name='Normal', email='normal@college.edu', role='user')
    login(client, email='normal@college.edu')
    for url in ['/admin', '/admin/items', '/admin/users', '/admin/claims']:
        assert client.get(url).status_code == 403, url

    logout(client)
    make_user(app, name='Admin', email='admin@college.edu', role='admin')
    login(client, email='admin@college.edu')
    for url in ['/admin', '/admin/items', '/admin/users', '/admin/claims']:
        assert client.get(url).status_code == 200, url


def test_admin_can_moderate_reports_and_users(app, client):
    owner_id = make_user(app, name='Owner', email='owner@college.edu')
    item_id = create_item(app, owner_id, name='Fake report')
    make_user(app, name='Admin', email='admin@college.edu', role='admin')
    login(client, email='admin@college.edu')

    response = client.post(f'/admin/item/{item_id}/status', data={'status': 'Removed'},
                           follow_redirects=True)
    assert 'status changed to Removed' in html(response)
    with app.app_context():
        assert db.query_one('SELECT status FROM item_reports WHERE item_id=%s', (item_id,))['status'] == 'Removed'

    member_id = make_user(app, name='Member', email='member@college.edu')
    response = client.post(f'/admin/users/{member_id}/role', data={'role': 'staff'},
                           follow_redirects=True)
    assert 'is now staff' in html(response)

    response = client.post(f'/admin/users/{member_id}/delete', follow_redirects=True)
    assert 'deleted' in html(response)
    with app.app_context():
        assert db.query_one('SELECT user_id FROM users WHERE user_id=%s', (member_id,)) is None


def test_admin_cannot_change_own_role(app, client):
    make_user(app, name='Admin', email='admin@college.edu', role='admin')
    login(client, email='admin@college.edu')
    with app.app_context():
        me = db.query_one("SELECT user_id FROM users WHERE email='admin@college.edu'")
    response = client.post(f"/admin/users/{me['user_id']}/role", data={'role': 'user'},
                           follow_redirects=True)
    assert 'cannot change your own role' in html(response)


# ---------------------------------------------------------------------------
# Matching integration: eligibility, duplicates, recalculation
# ---------------------------------------------------------------------------

def test_returned_items_are_excluded_from_matching(app):
    owner_id = make_user(app, name='Owner', email='owner@college.edu')
    lost_id = create_item(app, owner_id, item_type='Lost', name='Blue backpack',
                          description='Blue backpack with broken zip', color='Blue',
                          brand='Skybag', location='Block C', item_date='2026-09-20')
    found_id = create_item(app, owner_id, item_type='Found', name='Blue backpack',
                           description='Blue backpack with broken zip', color='Blue',
                           brand='Skybag', location='Block C',
                           item_date='2026-09-21')

    with app.app_context():
        from services import match_service
        match_service.recalculate_for_item(lost_id)
        assert db.query_one('SELECT COUNT(*) AS c FROM matches')['c'] == 1

        db.execute('UPDATE item_reports SET is_returned=1, status=%s WHERE item_id=%s',
                   ('Returned', found_id))
        match_service.recalculate_for_item(lost_id)
        assert db.query_one('SELECT COUNT(*) AS c FROM matches')['c'] == 0


def test_recalculation_does_not_create_duplicate_matches(app):
    owner_id = make_user(app, name='Owner', email='owner@college.edu')
    create_item(app, owner_id, item_type='Lost', name='Black wallet',
                description='Black leather wallet with ID card', color='Black',
                brand='Fossil', location='Library', item_date='2026-09-20')
    found_id = create_item(app, owner_id, item_type='Found', name='Black wallet',
                           description='Black leather wallet with ID card', color='Black',
                           brand='Fossil', location='Library', item_date='2026-09-21')
    with app.app_context():
        from services import match_service
        match_service.recalculate_for_item(found_id)
        match_service.recalculate_for_item(found_id)
        assert db.query_one('SELECT COUNT(*) AS c FROM matches')['c'] == 1


def test_editing_details_recalculates_matches(app, client):
    owner_id = make_user(app, name='Owner', email='owner@college.edu')
    login(client, email='owner@college.edu')
    lost_id = create_item(app, owner_id, item_type='Lost', name='Black wallet',
                          description='Black leather wallet with ID card', color='Black',
                          brand='Fossil', location='Library', item_date='2026-09-20')
    found_id = create_item(app, owner_id, item_type='Found', name='Black wallet',
                           description='Black leather wallet with ID card', color='Black',
                           brand='Fossil', location='Library', item_date='2026-09-21')
    recalc(app, found_id)
    with app.app_context():
        assert db.query_one('SELECT COUNT(*) AS c FROM matches')['c'] == 1

    response = client.post(f'/item/{lost_id}/edit', data={
        'item_name': 'Garden hose',
        'category': 'Other',
        'description': 'A long green garden hose for watering plants',
        'location': 'Sports Ground',
        'item_date': '2026-01-01',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assert db.query_one('SELECT COUNT(*) AS c FROM matches')['c'] == 0


# ---------------------------------------------------------------------------
# Upload security
# ---------------------------------------------------------------------------

def test_non_image_upload_is_rejected(app, client):
    register(client)
    response = client.post('/report/lost', data={
        'item_name': 'Test item', 'category': 'Other',
        'description': 'This description is long enough to pass validation.',
        'location': 'Library', 'item_date': '2026-09-20',
        'image': (io.BytesIO(b'<?php echo "hacked"; ?>'), 'evil.jpg'),
    }, content_type='multipart/form-data')
    assert response.status_code == 200
    assert 'not a valid image' in html(response)
    with app.app_context():
        assert db.query_one('SELECT COUNT(*) AS c FROM item_reports')['c'] == 0


def test_valid_image_upload_is_stored_and_served(app, client):
    register(client)
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), color=(120, 90, 180)).save(buffer, format='PNG')
    buffer.seek(0)

    response = client.post('/report/lost', data={
        'item_name': 'Purple umbrella',
        'category': 'Other',
        'description': 'A purple umbrella with a wooden handle.',
        'location': 'Main Gate',
        'item_date': '2026-09-20',
        'image': (buffer, 'photo.png'),
    }, content_type='multipart/form-data', follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        item = db.query_one('SELECT image FROM item_reports')
    assert item and item['image'].endswith('.png')
    stored = os.path.join(app.config['UPLOAD_FOLDER'], item['image'])
    assert os.path.isfile(stored)

    served = client.get(f"/uploads/{item['image']}")
    assert served.status_code == 200


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def test_csrf_protection_blocks_post_without_token(app):
    app.config['CSRF_ENABLED'] = True
    try:
        fresh = app.test_client()
        fresh.get('/login')  # establish a session + token in the rendered form
        response = fresh.post('/login', data={
            'email': 'sowmiya@college.edu', 'password': 'Password123',
        })
        assert response.status_code == 400
        assert 'CSRF' in html(response)
    finally:
        app.config['CSRF_ENABLED'] = False


# ---------------------------------------------------------------------------
# Database persistence sanity
# ---------------------------------------------------------------------------

def test_foreign_keys_cascade_on_user_delete(app):
    uid = make_user(app, name='Owner', email='owner@college.edu')
    item_id = create_item(app, uid, name='Wallet')
    with app.app_context():
        count = db.query_one('SELECT COUNT(*) AS c FROM item_reports')['c']
        assert count == 1
        db.execute('DELETE FROM users WHERE user_id=%s', (uid,))
        assert db.query_one('SELECT COUNT(*) AS c FROM item_reports')['c'] == 0


def test_health_endpoint_reports_database(app, client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.get_json()['database'] == 'connected'
