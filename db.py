"""MySQL access layer for Lost & Found+.

Every query uses parameterised placeholders (%s) so user input is never
concatenated into SQL.

The connection helpers support both a local MySQL server and a hosted MySQL
service. Hosted services usually require TLS, so set MYSQL_SSL=true (or use a
``mysql://`` URL with ``?ssl-mode=REQUIRED``).
"""
import os
import re

import mysql.connector
from mysql.connector import Error
from flask import g, current_app, has_app_context

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_$-]+$')
_UNSET = object()

# Tables and columns required by the application. Used by /health and
# scripts/check_db.py to distinguish "MySQL is reachable" from "schema is ready".
REQUIRED_TABLES = ('users', 'item_reports', 'claims', 'matches', 'notifications')
REQUIRED_COLUMNS = {
    'users': {
        'user_id', 'name', 'email', 'password', 'role', 'student_id',
        'department', 'phone', 'created_at', 'updated_at',
    },
    'item_reports': {
        'item_id', 'user_id', 'item_name', 'category', 'item_type',
        'description', 'color', 'brand', 'location', 'distinctive_marks',
        'item_date', 'image', 'status', 'is_returned', 'created_at', 'updated_at',
    },
    'claims': {
        'claim_id', 'claimant_id', 'item_id', 'message',
        'verification_details', 'status', 'admin_response', 'created_at',
        'updated_at',
    },
    'matches': {
        'match_id', 'lost_item_id', 'found_item_id', 'match_score',
        'match_reasons', 'status', 'created_at', 'updated_at',
    },
    'notifications': {
        'notification_id', 'user_id', 'match_id', 'message', 'is_read',
        'created_at',
    },
}


def _setting(config, name, default=None):
    if config is not None and name in config:
        return config[name]
    import config as root_config
    return getattr(root_config.Config, name, default)


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _connection_kwargs(database=_UNSET, config=None):
    """Build connector arguments for local or hosted MySQL."""
    if config is None:
        config = current_app.config if has_app_context() else None

    kwargs = {
        'host': _setting(config, 'MYSQL_HOST', 'localhost'),
        'port': _as_int(_setting(config, 'MYSQL_PORT', 3306), 3306),
        'user': _setting(config, 'MYSQL_USER', 'root'),
        'password': _setting(config, 'MYSQL_PASSWORD', ''),
        'charset': 'utf8mb4',
        'autocommit': False,
        'connection_timeout': _as_int(
            _setting(config, 'MYSQL_CONNECT_TIMEOUT', 15), 15
        ),
        'read_timeout': _as_int(_setting(config, 'MYSQL_READ_TIMEOUT', 30), 30),
        'write_timeout': _as_int(_setting(config, 'MYSQL_WRITE_TIMEOUT', 30), 30),
    }

    if database is _UNSET:
        database = _setting(config, 'MYSQL_DATABASE', None)
    if database:
        kwargs['database'] = database

    if _as_bool(_setting(config, 'MYSQL_SSL', False)):
        kwargs['ssl_disabled'] = False
        ssl_ca = _setting(config, 'MYSQL_SSL_CA', None)
        ssl_cert = _setting(config, 'MYSQL_SSL_CERT', None)
        ssl_key = _setting(config, 'MYSQL_SSL_KEY', None)
        if ssl_ca:
            kwargs['ssl_ca'] = ssl_ca
        if ssl_cert:
            kwargs['ssl_cert'] = ssl_cert
        if ssl_key:
            kwargs['ssl_key'] = ssl_key
        kwargs['ssl_verify_cert'] = _as_bool(
            _setting(config, 'MYSQL_SSL_VERIFY', False)
        )
        kwargs['ssl_verify_identity'] = _as_bool(
            _setting(config, 'MYSQL_SSL_VERIFY_IDENTITY', False)
        )
    # When MYSQL_SSL is not set, leave the connector's default negotiation in
    # place. This keeps local MySQL (with or without TLS) and hosted providers
    # that require TLS working without extra configuration.

    return kwargs


def _connect_with_config(config, database=_UNSET):
    return mysql.connector.connect(
        **_connection_kwargs(database=database, config=config)
    )


def _connect(database=None):
    """Open a connection using the current Flask app's configuration."""
    return _connect_with_config(
        current_app.config,
        database if database is not None else _UNSET,
    )


def get_db():
    """Return one connection per request."""
    if 'db' not in g:
        g.db = _connect()
    return g.db


def close_db(exc=None):
    conn = g.pop('db', None)
    if conn is not None:
        try:
            if exc is None:
                conn.commit()
        except Error:
            pass
        finally:
            conn.close()


def query_all(sql, params=()):
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def query_one(sql, params=()):
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def execute(sql, params=(), commit=True):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        last_id = cur.lastrowid
        if commit:
            conn.commit()
        return last_id
    finally:
        cur.close()


def schema_status():
    """Return which required tables/columns are missing in the current DB.

    This is a read-only check. It never modifies the database.
    """
    db_name = _setting(current_app.config, 'MYSQL_DATABASE', None)
    table_rows = query_all(
        """SELECT TABLE_NAME AS table_name
           FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = %s""",
        (db_name,),
    )
    column_rows = query_all(
        """SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = %s""",
        (db_name,),
    )

    present_tables = {row['table_name'] for row in table_rows}
    present_columns = {}
    for row in column_rows:
        present_columns.setdefault(row['table_name'], set()).add(row['column_name'])

    missing_tables = [table for table in REQUIRED_TABLES if table not in present_tables]
    missing_columns = {}
    for table, required in REQUIRED_COLUMNS.items():
        if table not in present_tables:
            continue
        missing = sorted(required - present_columns.get(table, set()))
        if missing:
            missing_columns[table] = missing

    return {
        'database': db_name,
        'ready': not missing_tables and not missing_columns,
        'missing_tables': missing_tables,
        'missing_columns': missing_columns,
    }


def _split_statements(sql):
    """Split a .sql file into statements, ignoring ';' inside strings/comments."""
    statements = []
    buffer = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ''

        if in_line_comment:
            if ch == '\n':
                in_line_comment = False
                buffer.append(ch)
            i += 1
            continue
        if in_block_comment:
            if ch == '*' and nxt == '/':
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if not in_single and not in_double:
            if ch == '-' and nxt == '-':
                in_line_comment = True
                i += 2
                continue
            if ch == '#':
                in_line_comment = True
                i += 1
                continue
            if ch == '/' and nxt == '*':
                in_block_comment = True
                i += 2
                continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ';' and not in_single and not in_double:
            stmt = ''.join(buffer).strip()
            if stmt:
                statements.append(stmt)
            buffer = []
            i += 1
            continue
        buffer.append(ch)
        i += 1
    tail = ''.join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _apply_schema(conn, lock_name=None):
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as fh:
        statements = _split_statements(fh.read())
    cur = conn.cursor()
    locked = False
    try:
        if lock_name:
            # Gunicorn can import the app in more than one worker at the same
            # time. A MySQL advisory lock ensures only one process runs the
            # CREATE TABLE statements; the others wait and then see the tables.
            cur.execute('SELECT GET_LOCK(%s, 30)', (lock_name,))
            row = cur.fetchone()
            locked = bool(row and row[0] == 1)
            if not locked:
                raise Error(
                    'Could not acquire the schema setup lock; another process '
                    'may still be initialising the database.'
                )
        for stmt in statements:
            upper = stmt.strip().upper()
            if upper.startswith('CREATE DATABASE') or upper.startswith('USE '):
                continue
            cur.execute(stmt)
        conn.commit()
    finally:
        try:
            cur.close()
        finally:
            if locked:
                release = conn.cursor()
                try:
                    release.execute('SELECT RELEASE_LOCK(%s)', (lock_name,))
                    release.fetchall()
                except Error:
                    pass
                finally:
                    release.close()
    return len(statements)


def init_database(app):
    """Create the database (only if needed) and apply schema.sql safely.

    schema.sql only contains CREATE ... IF NOT EXISTS statements, so existing
    tables and rows are preserved.

    Hosted MySQL accounts often cannot run CREATE DATABASE. If the configured
    database already exists, the schema is applied directly without trying to
    create the database or requiring CREATE DATABASE privileges.
    """
    db_name = app.config['MYSQL_DATABASE']
    if not _IDENTIFIER_RE.fullmatch(db_name or ''):
        raise ValueError(
            'MYSQL_DATABASE may only contain letters, numbers, underscores, '
            'dollar signs and hyphens.'
        )

    try:
        conn = _connect_with_config(app.config, db_name)
    except Error as exc:
        # 1049 = ER_BAD_DB_ERROR (database does not exist).
        if getattr(exc, 'errno', None) != 1049:
            raise
        base = _connect_with_config(app.config, None)
        try:
            cur = base.cursor()
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            base.commit()
        finally:
            base.close()
        conn = _connect_with_config(app.config, db_name)

    try:
        # Keep the advisory lock name unique per database and within MySQL's
        # 64-character limit.
        lock_name = f'lfp_schema_{db_name}'[:64]
        return _apply_schema(conn, lock_name=lock_name)
    finally:
        conn.close()
