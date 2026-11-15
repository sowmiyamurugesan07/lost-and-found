"""Lost & Found+ — Smart College Lost & Found System.

Flask + MySQL. Run with:  python app.py
"""
import logging
import os
import re
import uuid
from datetime import date, datetime
from functools import wraps
from urllib.parse import urljoin, urlparse

import mysql.connector
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import db
from config import config
from services import matching, match_service


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config_name: str | None = None) -> Flask:
    if not config_name:
        config_name = os.environ.get('FLASK_ENV')
    if not config_name:
        on_render = (
            os.environ.get('RENDER', '').strip().lower() == 'true'
            or bool(os.environ.get('RENDER_SERVICE_ID'))
        )
        config_name = 'production' if on_render else 'development'
    app = Flask(__name__)
    app.config.from_object(config.get(config_name, config['default']))
    # Keep deployment logs useful: the default root logger suppresses INFO,
    # which would hide the "Database schema ready" boot message on Render.
    app.logger.setLevel(logging.INFO)
    if (
        config_name == 'production'
        and app.config.get('SECRET_KEY') == 'dev-secret-key-change-in-production'
    ):
        app.logger.warning(
            'SECRET_KEY is not set; using the insecure development default. '
            'Set SECRET_KEY in the hosting dashboard.'
        )
    if app.config.get('TRUST_PROXY'):
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1
        )
    upload_folder = app.config['UPLOAD_FOLDER']
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(app.root_path, upload_folder)
    app.config['UPLOAD_FOLDER'] = os.path.abspath(upload_folder)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    register_hooks(app)
    register_routes(app)
    register_error_handlers(app)

    app.teardown_appcontext(db.close_db)

    @app.context_processor
    def inject_globals():
        user = current_user()
        unread = 0
        if user:
            try:
                unread = match_service.count_unread_notifications(user['user_id'])
            except mysql.connector.Error:
                unread = 0
        return {
            'current_user': user,
            'unread_notifications': unread,
            'categories': CATEGORIES,
            'colours': COLOURS,
            'now': datetime.now(),
        }

    app.jinja_env.globals['csrf_token'] = csrf_token
    app.jinja_env.filters['pretty_date'] = pretty_date
    app.jinja_env.filters['status_class'] = status_class
    app.jinja_env.filters['initial'] = lambda value: (value or '?')[:1].upper()

    return app


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATEGORIES = [
    'Electronics', 'Accessories', 'Bags & Luggage', 'Books & Stationery',
    'ID Cards & Documents', 'Keys', 'Clothing', 'Sports Equipment',
    'Water Bottles', 'Jewellery', 'Other',
]

COLOURS = [
    'Black', 'White', 'Grey', 'Silver', 'Blue', 'Navy', 'Red', 'Maroon',
    'Green', 'Yellow', 'Orange', 'Pink', 'Purple', 'Brown', 'Beige',
    'Multi-colour', 'Other',
]

ROLES = ('user', 'staff', 'admin')
MAX_IMAGE_BYTES = 5 * 1024 * 1024
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')


# ---------------------------------------------------------------------------
# Authentication / CSRF helpers
# ---------------------------------------------------------------------------

def csrf_token() -> str:
    token = session.get('_csrf_token')
    if not token:
        token = uuid.uuid4().hex
        session['_csrf_token'] = token
    return token


def validate_csrf() -> None:
    if not app_config('CSRF_ENABLED', True):
        return
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    expected = session.get('_csrf_token')
    supplied = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    if not expected or not supplied or not _constant_eq(expected, supplied):
        abort(400, description='Invalid or missing CSRF token. Please reload the page and try again.')


def _constant_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def app_config(key, default=None):
    try:
        from flask import current_app
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


def current_user():
    """Load the authenticated user from MySQL using session['user_id']."""
    if g.get('user') is not None:
        return g.user
    user_id = session.get('user_id')
    if not user_id:
        g.user = None
        return None
    try:
        user = db.query_one(
            """SELECT user_id, name, email, role, student_id, department, phone,
                      created_at
               FROM users WHERE user_id = %s""",
            (user_id,),
        )
    except mysql.connector.Error:
        user = None
    if user is None:
        session.clear()
    g.user = user
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash('Please sign in to continue.', 'error')
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            flash('Please sign in to continue.', 'error')
            return redirect(url_for('login', next=request.path))
        if user['role'] != 'admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def is_safe_next(target: str | None) -> bool:
    if not target:
        return False
    base = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in ('http', 'https') and candidate.netloc == base.netloc


def register_hooks(app):
    @app.before_request
    def before_request():
        g.user = None
        validate_csrf()
        current_user()


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def pretty_date(value):
    if value is None:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], '%Y-%m-%d').date()
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime('%d %b %Y, %I:%M %p')
    return value.strftime('%d %b %Y')


def status_class(status: str) -> str:
    mapping = {
        'active': 'badge-active', 'verified': 'badge-verified',
        'matched': 'badge-matched', 'returned': 'badge-returned',
        'removed': 'badge-removed', 'pending': 'badge-pending',
        'approved': 'badge-approved', 'rejected': 'badge-rejected',
        'completed': 'badge-returned', 'lost': 'badge-lost', 'found': 'badge-found',
    }
    return mapping.get((status or '').lower(), 'badge-active')


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app_config('ALLOWED_EXTENSIONS', set())


def save_upload(file_storage):
    """Validate and store an uploaded image. Returns stored filename or raises ValueError."""
    if file_storage is None or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError('Please upload a JPG, PNG, GIF or WEBP image.')

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size == 0:
        raise ValueError('The uploaded image is empty.')
    if size > max_image_bytes():
        raise ValueError('The image is larger than 5 MB.')

    # Verify the bytes really are an image (prevents renamed scripts).
    try:
        from PIL import Image
        image = Image.open(file_storage.stream)
        image_format = (image.format or '').lower()
        image.verify()
        file_storage.stream.seek(0)
    except Exception:
        raise ValueError('That file is not a valid image.')

    ext_map = {'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png', 'gif': 'gif', 'webp': 'webp'}
    ext = ext_map.get(image_format) or file_storage.filename.rsplit('.', 1)[1].lower()
    if ext not in app_config('ALLOWED_EXTENSIONS', set()):
        raise ValueError('Unsupported image format.')

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    destination = os.path.join(app_config('UPLOAD_FOLDER'), stored_name)
    file_storage.stream.seek(0)
    file_storage.save(destination)
    return stored_name


def max_image_bytes():
    return int(app_config('MAX_IMAGE_BYTES', MAX_IMAGE_BYTES))


def delete_upload(filename):
    if not filename:
        return
    safe = os.path.basename(filename)
    path = os.path.join(app_config('UPLOAD_FOLDER'), safe)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def validate_report_form(form):
    """Return (data, errors). Only server-side values are trusted."""
    errors = {}
    name = (form.get('item_name') or '').strip()
    category = (form.get('category') or '').strip()
    description = (form.get('description') or '').strip()
    color = (form.get('color') or '').strip()
    brand = (form.get('brand') or '').strip()
    location = (form.get('location') or '').strip()
    marks = (form.get('distinctive_marks') or '').strip()
    item_date = (form.get('item_date') or '').strip()

    if not (2 <= len(name) <= 200):
        errors['item_name'] = 'Please enter an item name between 2 and 200 characters.'
    if category not in CATEGORIES:
        errors['category'] = 'Please choose a valid category.'
    if len(description) < 10:
        errors['description'] = 'Please describe the item in at least 10 characters.'
    elif len(description) > 3000:
        errors['description'] = 'Description must be under 3000 characters.'
    if len(color) > 50:
        errors['color'] = 'Colour is too long.'
    if len(brand) > 100:
        errors['brand'] = 'Brand is too long.'
    if not (2 <= len(location) <= 200):
        errors['location'] = 'Please enter where the item was lost or found.'
    if len(marks) > 1000:
        errors['distinctive_marks'] = 'Identifying marks must be under 1000 characters.'
    parsed_date = None
    if not item_date:
        errors['item_date'] = 'Please choose a date.'
    else:
        try:
            parsed_date = datetime.strptime(item_date, '%Y-%m-%d').date()
            if parsed_date > date.today():
                errors['item_date'] = 'The date cannot be in the future.'
        except ValueError:
            errors['item_date'] = 'Please use a valid date.'

    data = {
        'item_name': name, 'category': category, 'description': description,
        'color': color or None, 'brand': brand or None,
        'location': location, 'distinctive_marks': marks or None,
        'item_date': parsed_date,
    }
    return data, errors


def user_can_view_contact(user, item, has_approved_claim=False):
    if not user:
        return False
    return (
        user['role'] == 'admin'
        or user['user_id'] == item['user_id']
        or has_approved_claim
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app):

    @app.route('/')
    def index():
        stats = {
            'lost': _scalar("SELECT COUNT(*) FROM item_reports WHERE item_type='Lost' AND status <> 'Removed'"),
            'found': _scalar("SELECT COUNT(*) FROM item_reports WHERE item_type='Found' AND status <> 'Removed'"),
            'returned': _scalar("SELECT COUNT(*) FROM item_reports WHERE is_returned = 1"),
            'users': _scalar("SELECT COUNT(*) FROM users"),
        }
        recent = db.query_all(
            """SELECT i.*, u.name AS reporter_name
               FROM item_reports i JOIN users u ON u.user_id = i.user_id
               WHERE i.status <> 'Removed'
               ORDER BY i.created_at DESC LIMIT 6"""
        )
        return render_template('index.html', stats=stats, recent=recent)

    # ---------------- Auth ----------------

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user():
            return redirect(url_for('dashboard'))

        form = {'name': '', 'email': '', 'student_id': '', 'department': '', 'phone': ''}
        if request.method == 'POST':
            form = {k: (request.form.get(k) or '').strip() for k in form}
            password = request.form.get('password') or ''
            confirm = request.form.get('confirm_password') or ''
            errors = {}

            if not (2 <= len(form['name']) <= 100):
                errors['name'] = 'Please enter your full name.'
            if not EMAIL_RE.match(form['email']) or len(form['email']) > 150:
                errors['email'] = 'Please enter a valid email address.'
            if len(password) < 8:
                errors['password'] = 'Password must be at least 8 characters.'
            elif not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
                errors['password'] = 'Password must contain both letters and numbers.'
            if password != confirm:
                errors['confirm_password'] = 'Passwords do not match.'
            if form['phone'] and not re.match(r'^[0-9+\-\s()]{7,20}$', form['phone']):
                errors['phone'] = 'Please enter a valid phone number.'

            if not errors:
                existing = db.query_one('SELECT user_id FROM users WHERE email = %s', (form['email'].lower(),))
                if existing:
                    errors['email'] = 'An account with this email already exists.'

            if errors:
                for message in errors.values():
                    flash(message, 'error')
                return render_template('register.html', form=form, errors=errors)

            user_id = db.execute(
                """INSERT INTO users (name, email, password, role, student_id, department, phone)
                   VALUES (%s, %s, %s, 'user', %s, %s, %s)""",
                (form['name'], form['email'].lower(), generate_password_hash(password),
                 form['student_id'] or None, form['department'] or None, form['phone'] or None),
            )
            session.clear()
            session['user_id'] = user_id
            session.permanent = True
            csrf_token()
            flash(f"Welcome to Lost & Found+, {form['name'].split()[0]}! Your account is ready.", 'success')
            return redirect(url_for('dashboard'))

        return render_template('register.html', form=form, errors={})

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user():
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            email = (request.form.get('email') or '').strip().lower()
            password = request.form.get('password') or ''
            user = db.query_one('SELECT * FROM users WHERE email = %s', (email,))
            if not user or not check_password_hash(user['password'], password):
                flash('Incorrect email or password.', 'error')
                return render_template('login.html', email=email), 401

            # Fresh session on login prevents session fixation / data leakage.
            session.clear()
            session['user_id'] = user['user_id']
            session.permanent = True
            csrf_token()
            flash(f"Welcome back, {user['name'].split()[0]}!", 'success')

            nxt = request.args.get('next') or request.form.get('next')
            if is_safe_next(nxt):
                return redirect(nxt)
            return redirect(url_for('admin_dashboard') if user['role'] == 'admin' else url_for('dashboard'))

        return render_template('login.html', email='')

    @app.route('/logout', methods=['POST'])
    @login_required
    def logout():
        session.clear()
        flash('You have been signed out safely.', 'success')
        return redirect(url_for('index'))

    # ---------------- Browse / search ----------------

    @app.route('/browse')
    def browse():
        q = (request.args.get('q') or '').strip()
        item_type = (request.args.get('type') or '').strip().capitalize()
        category = (request.args.get('category') or '').strip()
        color = (request.args.get('color') or '').strip()
        location = (request.args.get('location') or '').strip()
        date_from = (request.args.get('date_from') or '').strip()
        date_to = (request.args.get('date_to') or '').strip()
        sort = (request.args.get('sort') or 'newest').strip()
        page = max(1, _to_int(request.args.get('page'), 1))
        per_page = 9

        where = ["i.status <> 'Removed'"]
        params = []
        if q:
            where.append("(i.item_name LIKE %s OR i.description LIKE %s OR i.brand LIKE %s OR i.distinctive_marks LIKE %s)")
            like = f"%{q}%"
            params += [like, like, like, like]
        if item_type in ('Lost', 'Found'):
            where.append("i.item_type = %s")
            params.append(item_type)
        if category in CATEGORIES:
            where.append("i.category = %s")
            params.append(category)
        if color:
            where.append("i.color = %s")
            params.append(color)
        if location:
            where.append("i.location LIKE %s")
            params.append(f"%{location}%")
        if date_from:
            try:
                datetime.strptime(date_from, '%Y-%m-%d')
                where.append("i.item_date >= %s")
                params.append(date_from)
            except ValueError:
                date_from = ''
        if date_to:
            try:
                datetime.strptime(date_to, '%Y-%m-%d')
                where.append("i.item_date <= %s")
                params.append(date_to)
            except ValueError:
                date_to = ''

        where_sql = ' AND '.join(where)
        order_sql = {
            'newest': 'i.created_at DESC',
            'oldest': 'i.created_at ASC',
            'relevance': (
                "(CASE WHEN i.item_name LIKE %s THEN 0 "
                "WHEN i.description LIKE %s THEN 1 ELSE 2 END), i.created_at DESC"
                if q else 'i.created_at DESC'
            ),
        }.get(sort, 'i.created_at DESC')
        count_params = list(params)
        if sort == 'relevance' and q:
            params += [f"%{q}%", f"%{q}%"]

        total = _scalar(
            f"SELECT COUNT(*) FROM item_reports i WHERE {where_sql}", tuple(count_params)
        )
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        offset = (page - 1) * per_page

        items = db.query_all(
            f"""SELECT i.*, u.name AS reporter_name
                FROM item_reports i JOIN users u ON u.user_id = i.user_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s""",
            tuple(params + [per_page, offset]),
        )
        return render_template(
            'browse.html', items=items, total=total, page=page, pages=pages,
            filters={'q': q, 'type': item_type, 'category': category, 'color': color,
                     'location': location, 'date_from': date_from, 'date_to': date_to,
                     'sort': sort},
        )

    # ---------------- Item detail ----------------

    @app.route('/item/<int:item_id>')
    def item_detail(item_id):
        item = db.query_one(
            """SELECT i.*, u.name AS reporter_name, u.email AS reporter_email,
                      u.phone AS reporter_phone, u.department AS reporter_department,
                      u.student_id AS reporter_student_id
               FROM item_reports i JOIN users u ON u.user_id = i.user_id
               WHERE i.item_id = %s""",
            (item_id,),
        )
        if not item:
            abort(404)
        user = current_user()
        if item['status'] == 'Removed' and (not user or user['role'] != 'admin'):
            abort(404)

        owner = bool(user and user['user_id'] == item['user_id'])
        admin = bool(user and user['role'] == 'admin')

        claims = []
        my_claim = None
        if owner or admin:
            claims = db.query_all(
                """SELECT c.*, u.name AS claimant_name, u.email AS claimant_email,
                          u.phone AS claimant_phone
                   FROM claims c JOIN users u ON u.user_id = c.claimant_id
                   WHERE c.item_id = %s ORDER BY c.created_at DESC""",
                (item_id,),
            )
        if user and not owner:
            my_claim = db.query_one(
                "SELECT * FROM claims WHERE item_id = %s AND claimant_id = %s ORDER BY claim_id DESC LIMIT 1",
                (item_id, user['user_id']),
            )

        has_approved = bool(my_claim and my_claim['status'] in ('Approved', 'Completed'))
        show_contact = user_can_view_contact(user, item, has_approved)

        matches = []
        if user and (owner or admin):
            matches = match_service.get_matches_for_item(item_id)

        can_claim = bool(
            user and item['item_type'] == 'Found' and not owner
            and not item['is_returned'] and item['status'] not in ('Removed', 'Returned')
            and not (my_claim and my_claim['status'] in ('Pending', 'Approved', 'Completed'))
        )
        return render_template(
            'item_detail.html', item=item, owner=owner, admin=admin, claims=claims,
            my_claim=my_claim, show_contact=show_contact, matches=matches,
            can_claim=can_claim,
        )

    # ---------------- Report lost / found ----------------

    @app.route('/report/lost', methods=['GET', 'POST'])
    @login_required
    def report_lost():
        return _handle_report('Lost')

    @app.route('/report/found', methods=['GET', 'POST'])
    @login_required
    def report_found():
        return _handle_report('Found')

    def _handle_report(item_type):
        form = {}
        if request.method == 'POST':
            form = request.form.to_dict()
            data, errors = validate_report_form(request.form)
            saved_image = None
            try:
                saved_image = save_upload(request.files.get('image'))
            except ValueError as exc:
                errors['image'] = str(exc)

            if errors:
                for message in errors.values():
                    flash(message, 'error')
                return render_template(
                    'report_item.html', item_type=item_type, form=form,
                    errors=errors, categories=CATEGORIES, colours=COLOURS,
                )

            user = current_user()
            item_id = db.execute(
                """INSERT INTO item_reports
                       (user_id, item_name, category, item_type, description, color,
                        brand, location, distinctive_marks, item_date, image, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Active')""",
                (user['user_id'], data['item_name'], data['category'], item_type,
                 data['description'], data['color'], data['brand'], data['location'],
                 data['distinctive_marks'], data['item_date'], saved_image),
            )
            try:
                matches = match_service.recalculate_for_item(item_id)
            except mysql.connector.Error:
                matches = []
            if matches:
                flash(
                    f"Report published! We found {len(matches)} possible match(es) — check your dashboard.",
                    'success',
                )
            else:
                flash('Report published successfully. We will notify you when a possible match appears.', 'success')
            return redirect(url_for('item_detail', item_id=item_id))

        return render_template(
            'report_item.html', item_type=item_type, form=form,
            errors={}, categories=CATEGORIES, colours=COLOURS,
        )

    @app.route('/item/<int:item_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_item(item_id):
        item = db.query_one('SELECT * FROM item_reports WHERE item_id = %s', (item_id,))
        if not item:
            abort(404)
        user = current_user()
        if user['user_id'] != item['user_id'] and user['role'] != 'admin':
            abort(403)
        if item['is_returned']:
            flash('Returned items can no longer be edited.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))

        if request.method == 'POST':
            data, errors = validate_report_form(request.form)
            new_image = item['image']
            old_image_to_delete = None
            uploaded = request.files.get('image')
            if uploaded and uploaded.filename:
                try:
                    new_image = save_upload(uploaded)
                    old_image_to_delete = item['image']
                except ValueError as exc:
                    errors['image'] = str(exc)

            if errors:
                for message in errors.values():
                    flash(message, 'error')
                return render_template(
                    'report_item.html', item_type=item['item_type'], form=request.form.to_dict(),
                    errors=errors, item=item, categories=CATEGORIES, colours=COLOURS,
                )

            db.execute(
                """UPDATE item_reports SET item_name=%s, category=%s, description=%s,
                       color=%s, brand=%s, location=%s, distinctive_marks=%s,
                       item_date=%s, image=%s WHERE item_id=%s""",
                (data['item_name'], data['category'], data['description'], data['color'],
                 data['brand'], data['location'], data['distinctive_marks'],
                 data['item_date'], new_image, item_id),
            )
            if old_image_to_delete:
                delete_upload(old_image_to_delete)
            match_service.recalculate_for_item(item_id)
            flash('Report updated. Matches were recalculated.', 'success')
            return redirect(url_for('item_detail', item_id=item_id))

        return render_template(
            'report_item.html', item_type=item['item_type'], form=item,
            errors={}, item=item, categories=CATEGORIES, colours=COLOURS,
        )

    @app.route('/item/<int:item_id>/delete', methods=['POST'])
    @login_required
    def delete_item(item_id):
        item = db.query_one('SELECT * FROM item_reports WHERE item_id = %s', (item_id,))
        if not item:
            abort(404)
        user = current_user()
        if user['user_id'] != item['user_id'] and user['role'] != 'admin':
            abort(403)
        if item['is_returned']:
            flash('Returned items are kept for records and cannot be deleted.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))
        db.execute('DELETE FROM item_reports WHERE item_id = %s', (item_id,))
        delete_upload(item['image'])
        flash('Report deleted.', 'success')
        return redirect(url_for('admin_items') if user['role'] == 'admin' else url_for('dashboard'))

    # ---------------- Dashboard ----------------

    @app.route('/dashboard')
    @login_required
    def dashboard():
        user = current_user()
        uid = user['user_id']
        counts = {
            'lost': _scalar("SELECT COUNT(*) FROM item_reports WHERE user_id=%s AND item_type='Lost'", (uid,)),
            'found': _scalar("SELECT COUNT(*) FROM item_reports WHERE user_id=%s AND item_type='Found'", (uid,)),
            'matches': len(match_service.get_matches_for_user(uid)),
            'claims': _scalar("SELECT COUNT(*) FROM claims WHERE claimant_id=%s", (uid,)),
            'returned': _scalar("SELECT COUNT(*) FROM item_reports WHERE user_id=%s AND is_returned=1", (uid,)),
        }
        my_items = db.query_all(
            """SELECT * FROM item_reports WHERE user_id = %s
               ORDER BY created_at DESC LIMIT 8""", (uid,)
        )
        matches = match_service.get_matches_for_user(uid, limit=6)
        my_claims = db.query_all(
            """SELECT c.*, i.item_name, i.item_type, i.image, i.location
               FROM claims c JOIN item_reports i ON i.item_id = c.item_id
               WHERE c.claimant_id = %s ORDER BY c.created_at DESC LIMIT 6""", (uid,)
        )
        received_claims = db.query_all(
            """SELECT c.*, i.item_name, u.name AS claimant_name
               FROM claims c
               JOIN item_reports i ON i.item_id = c.item_id
               JOIN users u ON u.user_id = c.claimant_id
               WHERE i.user_id = %s AND c.status = 'Pending'
               ORDER BY c.created_at DESC LIMIT 5""", (uid,)
        )
        notifications = match_service.recent_notifications(uid, limit=5)
        return render_template(
            'dashboard.html', counts=counts, my_items=my_items, matches=matches,
            my_claims=my_claims, received_claims=received_claims,
            notifications=notifications,
        )

    @app.route('/notifications/read', methods=['POST'])
    @login_required
    def notifications_read():
        match_service.mark_notifications_read(current_user()['user_id'])
        flash('Notifications marked as read.', 'success')
        return redirect(request.referrer or url_for('dashboard'))

    # ---------------- Claims ----------------

    @app.route('/claim/<int:item_id>', methods=['POST'])
    @login_required
    def create_claim(item_id):
        user = current_user()
        item = db.query_one('SELECT * FROM item_reports WHERE item_id = %s', (item_id,))
        if not item:
            abort(404)
        if item['item_type'] != 'Found':
            flash('Claims can only be made for found items.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))
        if item['user_id'] == user['user_id']:
            flash('You cannot claim your own report.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))
        if item['is_returned'] or item['status'] in ('Returned', 'Removed'):
            flash('This item is no longer available for claims.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))
        existing = db.query_one(
            """SELECT claim_id FROM claims
               WHERE item_id=%s AND claimant_id=%s AND status IN ('Pending','Approved','Completed')""",
            (item_id, user['user_id']),
        )
        if existing:
            flash('You already have an active claim for this item.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))

        message = (request.form.get('message') or '').strip()
        verification = (request.form.get('verification_details') or '').strip()
        if len(message) < 10:
            flash('Please write a short message (at least 10 characters) for the finder.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))
        if len(verification) < 10:
            flash('Please describe an identifying detail only the owner would know.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))
        if len(message) > 2000 or len(verification) > 2000:
            flash('Claim details are too long.', 'error')
            return redirect(url_for('item_detail', item_id=item_id))

        db.execute(
            """INSERT INTO claims (claimant_id, item_id, message, verification_details, status)
               VALUES (%s, %s, %s, %s, 'Pending')""",
            (user['user_id'], item_id, message, verification),
        )
        db.execute(
            "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
            (item['user_id'],
             f"New claim request from {user['name']} for '{item['item_name']}'."),
        )
        flash('Claim request sent. The finder or an admin will review it.', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/claims')
    @login_required
    def claims():
        user = current_user()
        submitted = db.query_all(
            """SELECT c.*, i.item_name, i.item_type, i.image, i.location, i.is_returned,
                      i.item_id, u.name AS owner_name
               FROM claims c
               JOIN item_reports i ON i.item_id = c.item_id
               JOIN users u ON u.user_id = i.user_id
               WHERE c.claimant_id = %s ORDER BY c.created_at DESC""",
            (user['user_id'],),
        )
        received = db.query_all(
            """SELECT c.*, i.item_name, i.item_id, i.is_returned,
                      u.name AS claimant_name, u.email AS claimant_email,
                      u.phone AS claimant_phone
               FROM claims c
               JOIN item_reports i ON i.item_id = c.item_id
               JOIN users u ON u.user_id = c.claimant_id
               WHERE i.user_id = %s ORDER BY c.created_at DESC""",
            (user['user_id'],),
        )
        return render_template('claims.html', submitted=submitted, received=received)

    def _get_claim_for_review(claim_id):
        claim = db.query_one(
            """SELECT c.*, i.user_id AS owner_id, i.item_name, i.item_type,
                      i.is_returned, i.status AS item_status
               FROM claims c JOIN item_reports i ON i.item_id = c.item_id
               WHERE c.claim_id = %s""",
            (claim_id,),
        )
        if not claim:
            abort(404)
        user = current_user()
        if user['role'] != 'admin' and claim['owner_id'] != user['user_id']:
            abort(403)
        return claim

    @app.route('/claims/<int:claim_id>/review', methods=['POST'])
    @login_required
    def review_claim(claim_id):
        claim = _get_claim_for_review(claim_id)
        action = (request.form.get('action') or '').strip().lower()
        response_text = (request.form.get('admin_response') or '').strip()[:1000]
        if action not in ('approve', 'reject'):
            flash('Unknown claim action.', 'error')
            return redirect(request.referrer or url_for('claims'))
        if claim['status'] in ('Completed',):
            flash('Completed claims cannot be changed.', 'error')
            return redirect(request.referrer or url_for('claims'))
        if claim['is_returned']:
            flash('This item is already returned.', 'error')
            return redirect(request.referrer or url_for('claims'))

        if action == 'approve':
            # Only one approved claim per item.
            other = db.query_one(
                """SELECT claim_id FROM claims
                   WHERE item_id = %s AND claim_id <> %s AND status = 'Approved'""",
                (claim['item_id'], claim_id),
            )
            if other:
                flash('Another claim is already approved for this item. Complete or reject it first.', 'error')
                return redirect(request.referrer or url_for('claims'))
            db.execute(
                "UPDATE claims SET status='Approved', admin_response=%s WHERE claim_id=%s",
                (response_text or 'Ownership verified.', claim_id),
            )
            db.execute("UPDATE item_reports SET status='Matched' WHERE item_id=%s", (claim['item_id'],))
            db.execute(
                "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
                (claim['claimant_id'],
                 f"Your claim for '{claim['item_name']}' was approved. Coordinate with the finder to collect it."),
            )
            flash('Claim approved. The claimant can now see contact details.', 'success')
        else:
            db.execute(
                "UPDATE claims SET status='Rejected', admin_response=%s WHERE claim_id=%s",
                (response_text or 'Ownership could not be verified.', claim_id),
            )
            db.execute(
                "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
                (claim['claimant_id'],
                 f"Your claim for '{claim['item_name']}' was rejected. You can submit a new claim with more details."),
            )
            flash('Claim rejected.', 'success')
        return redirect(request.referrer or url_for('claims'))

    @app.route('/claims/<int:claim_id>/complete', methods=['POST'])
    @login_required
    def complete_claim(claim_id):
        claim = _get_claim_for_review(claim_id)
        if claim['status'] != 'Approved':
            flash('Only an approved claim can be completed.', 'error')
            return redirect(request.referrer or url_for('claims'))
        if claim['is_returned']:
            flash('This item is already marked as returned.', 'error')
            return redirect(request.referrer or url_for('claims'))
        db.execute("UPDATE claims SET status='Completed' WHERE claim_id=%s", (claim_id,))
        db.execute(
            "UPDATE item_reports SET status='Returned', is_returned=1 WHERE item_id=%s",
            (claim['item_id'],),
        )
        # Close remaining pending claims for the same item.
        db.execute(
            """UPDATE claims SET status='Rejected',
                      admin_response='Item has already been returned to its verified owner.'
               WHERE item_id=%s AND claim_id<>%s AND status='Pending'""",
            (claim['item_id'], claim_id),
        )
        db.execute(
            "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
            (claim['claimant_id'],
             f"'{claim['item_name']}' is now marked as returned. Thanks for using Lost & Found+!"),
        )
        flash('Item marked as returned. The case is now closed.', 'success')
        return redirect(request.referrer or url_for('claims'))

    # ---------------- Profile ----------------

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        user = current_user()
        if request.method == 'POST':
            action = request.form.get('action', 'details')
            if action == 'password':
                current_pw = request.form.get('current_password') or ''
                new_pw = request.form.get('new_password') or ''
                confirm = request.form.get('confirm_password') or ''
                stored = db.query_one('SELECT password FROM users WHERE user_id=%s', (user['user_id'],))
                if not check_password_hash(stored['password'], current_pw):
                    flash('Your current password is incorrect.', 'error')
                elif len(new_pw) < 8 or not re.search(r'[A-Za-z]', new_pw) or not re.search(r'\d', new_pw):
                    flash('New password must be at least 8 characters with letters and numbers.', 'error')
                elif new_pw != confirm:
                    flash('New passwords do not match.', 'error')
                else:
                    db.execute('UPDATE users SET password=%s WHERE user_id=%s',
                               (generate_password_hash(new_pw), user['user_id']))
                    flash('Password updated successfully.', 'success')
            else:
                name = (request.form.get('name') or '').strip()
                student_id = (request.form.get('student_id') or '').strip()[:50]
                department = (request.form.get('department') or '').strip()[:100]
                phone = (request.form.get('phone') or '').strip()[:20]
                if not (2 <= len(name) <= 100):
                    flash('Please enter a valid name.', 'error')
                elif phone and not re.match(r'^[0-9+\-\s()]{7,20}$', phone):
                    flash('Please enter a valid phone number.', 'error')
                else:
                    db.execute(
                        """UPDATE users SET name=%s, student_id=%s, department=%s, phone=%s
                           WHERE user_id=%s""",
                        (name, student_id or None, department or None, phone or None, user['user_id']),
                    )
                    flash('Profile updated.', 'success')
                    g.pop('user', None)
            return redirect(url_for('profile'))

        stats = {
            'lost': _scalar("SELECT COUNT(*) FROM item_reports WHERE user_id=%s AND item_type='Lost'", (user['user_id'],)),
            'found': _scalar("SELECT COUNT(*) FROM item_reports WHERE user_id=%s AND item_type='Found'", (user['user_id'],)),
            'returned': _scalar("SELECT COUNT(*) FROM item_reports WHERE user_id=%s AND is_returned=1", (user['user_id'],)),
        }
        return render_template('profile.html', profile_user=user, stats=stats)

    # ---------------- Admin ----------------

    @app.route('/admin')
    @admin_required
    def admin_dashboard():
        stats = {
            'users': _scalar('SELECT COUNT(*) FROM users'),
            'lost': _scalar("SELECT COUNT(*) FROM item_reports WHERE item_type='Lost'"),
            'found': _scalar("SELECT COUNT(*) FROM item_reports WHERE item_type='Found'"),
            'pending_claims': _scalar("SELECT COUNT(*) FROM claims WHERE status='Pending'"),
            'returned': _scalar('SELECT COUNT(*) FROM item_reports WHERE is_returned=1'),
            'matches': _scalar("SELECT COUNT(*) FROM matches WHERE status='Active'"),
            'reports': _scalar('SELECT COUNT(*) FROM item_reports'),
        }
        recent_items = db.query_all(
            """SELECT i.*, u.name AS reporter_name FROM item_reports i
               JOIN users u ON u.user_id=i.user_id
               ORDER BY i.created_at DESC LIMIT 8"""
        )
        recent_claims = db.query_all(
            """SELECT c.*, i.item_name, i.item_id, u.name AS claimant_name
               FROM claims c JOIN item_reports i ON i.item_id=c.item_id
               JOIN users u ON u.user_id=c.claimant_id
               WHERE c.status='Pending' ORDER BY c.created_at DESC LIMIT 6"""
        )
        recent_users = db.query_all(
            """SELECT user_id, name, email, role, department, created_at
               FROM users ORDER BY created_at DESC LIMIT 6"""
        )
        return render_template(
            'admin_dashboard.html', stats=stats, recent_items=recent_items,
            recent_claims=recent_claims, recent_users=recent_users,
        )

    @app.route('/admin/items')
    @admin_required
    def admin_items():
        q = (request.args.get('q') or '').strip()
        item_type = (request.args.get('type') or '').strip().capitalize()
        status = (request.args.get('status') or '').strip()
        where = ['1=1']
        params = []
        if q:
            where.append('(i.item_name LIKE %s OR u.name LIKE %s OR u.email LIKE %s)')
            like = f'%{q}%'
            params += [like, like, like]
        if item_type in ('Lost', 'Found'):
            where.append('i.item_type=%s')
            params.append(item_type)
        if status:
            where.append('i.status=%s')
            params.append(status)
        items = db.query_all(
            f"""SELECT i.*, u.name AS reporter_name, u.email AS reporter_email
                FROM item_reports i JOIN users u ON u.user_id=i.user_id
                WHERE {' AND '.join(where)}
                ORDER BY i.created_at DESC LIMIT 100""",
            tuple(params),
        )
        return render_template('admin_items.html', items=items,
                               filters={'q': q, 'type': item_type, 'status': status})

    @app.route('/admin/item/<int:item_id>/status', methods=['POST'])
    @admin_required
    def admin_item_status(item_id):
        item = db.query_one('SELECT * FROM item_reports WHERE item_id=%s', (item_id,))
        if not item:
            abort(404)
        new_status = (request.form.get('status') or '').strip()
        if new_status not in ('Active', 'Verified', 'Matched', 'Removed'):
            flash('Invalid status.', 'error')
            return redirect(request.referrer or url_for('admin_items'))
        db.execute('UPDATE item_reports SET status=%s WHERE item_id=%s', (new_status, item_id))
        if new_status == 'Removed':
            db.execute('DELETE FROM matches WHERE lost_item_id=%s OR found_item_id=%s',
                       (item_id, item_id))
        else:
            match_service.recalculate_for_item(item_id)
        flash(f"Report status changed to {new_status}.", 'success')
        return redirect(request.referrer or url_for('admin_items'))

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        q = (request.args.get('q') or '').strip()
        role = (request.args.get('role') or '').strip()
        where = ['1=1']
        params = []
        if q:
            where.append('(name LIKE %s OR email LIKE %s OR student_id LIKE %s)')
            like = f'%{q}%'
            params += [like, like, like]
        if role in ROLES:
            where.append('role=%s')
            params.append(role)
        users = db.query_all(
            f"""SELECT u.*, (SELECT COUNT(*) FROM item_reports i WHERE i.user_id=u.user_id) AS report_count
                FROM users u WHERE {' AND '.join(where)}
                ORDER BY u.created_at DESC LIMIT 200""",
            tuple(params),
        )
        return render_template('admin_users.html', users=users,
                               filters={'q': q, 'role': role}, roles=ROLES)

    @app.route('/admin/users/<int:user_id>/role', methods=['POST'])
    @admin_required
    def admin_user_role(user_id):
        me = current_user()
        new_role = (request.form.get('role') or '').strip()
        if new_role not in ROLES:
            flash('Invalid role.', 'error')
            return redirect(url_for('admin_users'))
        if user_id == me['user_id']:
            flash('You cannot change your own role.', 'error')
            return redirect(url_for('admin_users'))
        target = db.query_one('SELECT user_id, name FROM users WHERE user_id=%s', (user_id,))
        if not target:
            abort(404)
        db.execute('UPDATE users SET role=%s WHERE user_id=%s', (new_role, user_id))
        flash(f"{target['name']} is now {new_role}.", 'success')
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_user_delete(user_id):
        me = current_user()
        if user_id == me['user_id']:
            flash('You cannot delete your own account while signed in.', 'error')
            return redirect(url_for('admin_users'))
        target = db.query_one('SELECT user_id, name, role FROM users WHERE user_id=%s', (user_id,))
        if not target:
            abort(404)
        if target['role'] == 'admin':
            admin_count = _scalar("SELECT COUNT(*) FROM users WHERE role='admin'")
            if admin_count <= 1:
                flash('You cannot delete the last administrator.', 'error')
                return redirect(url_for('admin_users'))
        db.execute('DELETE FROM users WHERE user_id=%s', (user_id,))
        flash(f"User {target['name']} and their reports were deleted.", 'success')
        return redirect(url_for('admin_users'))

    @app.route('/admin/claims')
    @admin_required
    def admin_claims():
        status = (request.args.get('status') or '').strip()
        where = '1=1'
        params = []
        if status in ('Pending', 'Approved', 'Rejected', 'Completed'):
            where = 'c.status = %s'
            params.append(status)
        claims = db.query_all(
            f"""SELECT c.*, i.item_name, i.item_id, i.item_type, i.location, i.is_returned,
                       u.name AS claimant_name, u.email AS claimant_email,
                       o.name AS owner_name, o.email AS owner_email
                FROM claims c
                JOIN item_reports i ON i.item_id=c.item_id
                JOIN users u ON u.user_id=c.claimant_id
                JOIN users o ON o.user_id=i.user_id
                WHERE {where} ORDER BY FIELD(c.status,'Pending','Approved','Completed','Rejected'),
                       c.created_at DESC LIMIT 200""",
            tuple(params),
        )
        return render_template('admin_claims.html', claims=claims, status=status)

    @app.route('/admin/matches/recalculate', methods=['POST'])
    @admin_required
    def admin_recalculate():
        count = match_service.recalculate_all()
        flash(f'Matches recalculated for {count} reports.', 'success')
        return redirect(url_for('admin_dashboard'))

    # ---------------- Uploads ----------------

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        safe = os.path.basename(filename)
        return send_from_directory(app_config('UPLOAD_FOLDER'), safe)

    # ---------------- Health ----------------

    @app.route('/health')
    def health():
        try:
            db.query_one('SELECT 1 AS ok')
        except mysql.connector.Error as exc:
            app.logger.warning('Health check: database unavailable: %s', exc)
            return {'status': 'degraded', 'database': 'unavailable'}, 503

        try:
            schema = db.schema_status()
        except mysql.connector.Error as exc:
            app.logger.warning('Health check: schema check failed: %s', exc)
            return {
                'status': 'degraded',
                'database': 'connected',
                'schema': 'unknown',
            }, 503

        payload = {
            'status': 'ok' if schema['ready'] else 'degraded',
            'database': 'connected',
            'schema': 'ready' if schema['ready'] else 'incomplete',
        }
        if not schema['ready']:
            payload['missing_tables'] = schema['missing_tables']
        return jsonify(payload), (200 if schema['ready'] else 503)


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _scalar(sql, params=()):
    row = db.query_one(sql, params)
    if not row:
        return 0
    return int(list(row.values())[0])


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

def register_error_handlers(app):

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template('403.html'), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template('404.html'), 404

    @app.errorhandler(413)
    def too_large(_error):
        flash('That upload is too large. Maximum size is 5 MB.', 'error')
        return redirect(request.referrer or url_for('index'))

    @app.errorhandler(400)
    def bad_request(error):
        return render_template('400.html', message=getattr(error, 'description', 'Bad request.')), 400

    @app.errorhandler(500)
    def server_error(_error):
        return render_template('500.html'), 500

    @app.errorhandler(mysql.connector.Error)
    def database_error(error):
        error_code = getattr(error, 'errno', None)
        app.logger.exception('Database error (code=%s): %s', error_code, error)

        # 1146 = table missing, 1054 = column missing. These mean the app can
        # reach MySQL but the schema has not been initialised (or is outdated).
        setup_error = error_code in (1054, 1146)
        connection_error = error_code in (
            1044, 1045, 1049, 1129, 1130, 2002, 2003, 2005, 2006, 2013, 2026, 2059,
        )
        return render_template(
            '500.html',
            database_error=connection_error or setup_error,
            setup_error=setup_error,
        ), 500


def _auto_initialise_database(application):
    """Create missing tables when AUTO_INIT_DB is enabled.

    This is opt-in locally and enabled by default on Render. schema.sql only
    contains CREATE ... IF NOT EXISTS statements, so existing data is never
    dropped. A failure is logged but does not stop the web server; /health
    will report the schema as incomplete.
    """
    if not application.config.get('AUTO_INIT_DB'):
        return
    try:
        with application.app_context():
            statements = db.init_database(application)
            status = db.schema_status()
        if status['ready']:
            application.logger.info(
                'Database schema ready for "%s" (%s statements checked).',
                application.config['MYSQL_DATABASE'], statements,
            )
        else:
            details = []
            if status['missing_tables']:
                details.append('missing tables: ' + ', '.join(status['missing_tables']))
            for table, columns in status['missing_columns'].items():
                details.append(f'{table} missing columns: ' + ', '.join(columns))
            application.logger.warning(
                'Database schema incomplete for "%s": %s.',
                application.config['MYSQL_DATABASE'],
                '; '.join(details) or 'unknown reason',
            )
    except Exception as exc:  # pragma: no cover - depends on deployment
        application.logger.exception(
            'Automatic database setup failed for "%s": %s. '
            'Check the database settings and run python scripts/init_db.py.',
            application.config['MYSQL_DATABASE'], exc,
        )


app = create_app()
_auto_initialise_database(app)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=app.config.get('DEBUG', True))
