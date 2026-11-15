# Lost & Found+

**A Smart Campus Lost & Found Management System Using Python and MySQL**

A complete BCA final-year project built with **Flask + MySQL**. Students can report lost or
found items, receive explainable smart-match suggestions, submit ownership claims, and track
every report from one private dashboard. Administrators get moderation tools, user management
and a claim-review queue.

---

## Contents

1. [Features](#1-features)
2. [Technology stack](#2-technology-stack)
3. [Project structure](#3-project-structure)
4. [Prerequisites](#4-prerequisites)
5. [Installation](#5-installation)
6. [MySQL setup](#6-mysql-setup)
7. [Environment file](#7-environment-file)
8. [Create the database](#8-create-the-database)
9. [Create the first administrator](#9-create-the-first-administrator)
10. [Run the application](#10-run-the-application)
11. [Run the automated tests](#11-run-the-automated-tests)
12. [How smart matching works](#12-how-smart-matching-works)
13. [Claim and privacy workflow](#13-claim-and-privacy-workflow)
14. [Security notes](#14-security-notes)
15. [Password recovery](#15-password-recovery)
16. [Troubleshooting](#16-troubleshooting)
17. [Deployment notes](#17-deployment-notes)
18. [Data-safety rules](#18-data-safety-rules)

---

## 1. Features

### Public
- Landing page with live statistics and recent reports.
- Browse every active lost/found report.
- Search by text, type, category, colour, location and date range.
- Sort by newest, oldest, item name or event date.
- Pagination and a responsive, accessible lavender/white design.
- Custom `400`, `403`, `404` and `500` pages.

### Member
- Registration and secure sign-in.
- Report lost items and report found items.
- Optional photo upload with real image validation.
- Private dashboard containing **only the signed-in member's data**.
- Possible-match cards with:
  - percentage score,
  - `Strong Possible Match` / `Possible Match` / `Weak Match` label,
  - human-readable reasons,
  - conflicts and missing details,
  - expandable per-factor score breakdown.
- In-app notifications when a new match or claim appears.
- Edit or delete your own reports; matches are recalculated automatically.
- Submit a claim with a private ownership-proof detail.
- Track sent and received claims.
- View contact details **only after** a claim is approved.
- Update profile details and change password.

### Administrator
- Protected admin dashboard with live statistics.
- Search/filter every report; change status or remove inappropriate reports.
- Review and approve/reject claims.
- Mark an approved claim as completed only after the physical handover.
- Manage user roles and delete accounts when necessary.
- Recalculate all matches.
- Cannot demote or delete the currently signed-in administrator.
- Cannot delete the last administrator.

### Smart matching
- Weighted, explainable scoring instead of a simple colour match.
- Pure-Python **TF-IDF + cosine similarity** for descriptions.
- Missing values never create points; remaining weights are re-normalised.
- Returned/removed items are excluded.
- Duplicate match rows are prevented by a unique database constraint.
- Editing a report recalculates its matches and clears stale rows.
- Category mismatch with unrelated names is capped so shared wording does not create
  false "possible" matches.

---

## 2. Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ (verified on Python 3.14.7) |
| Web framework | Flask 3.x |
| Database | MySQL Server 8.x (verified on MySQL 8.0.46) |
| DB driver | `mysql-connector-python` |
| Templates | Jinja2 |
| Styling | Hand-written responsive CSS 3 |
| Interactivity | Vanilla JavaScript |
| Passwords | Werkzeug PBKDF2 hashing |
| Image validation | Pillow |
| Tests | pytest + real MySQL test database |
| Config | `python-dotenv` + environment variables |

No SQLite fallback and no fake in-memory database are used. Every feature reads and writes
real MySQL rows.

---

## 3. Project structure

```text
project/
├── app.py                    # Flask app factory, routes, auth, claims, admin
├── config.py                 # Environment-driven configuration + match weights
├── db.py                     # MySQL connections, parameterised helpers, schema runner
├── schema.sql                # Re-runnable MySQL schema (never drops data)
├── requirements.txt
├── .env.example              # Template — copy to .env (never commit .env)
├── .gitignore
├── README.md                 # Full setup, security and troubleshooting guide
├── DEPLOY.md                 # Short Render + GitHub deployment checklist
├── services/
│   ├── matching.py           # Pure scoring engine (unit-testable, no Flask/MySQL)
│   └── match_service.py      # DB persistence, eligibility, notifications, recalculation
├── scripts/
│   ├── init_db.py            # Create DB + apply schema safely
│   ├── init_remote.py        # Interactive setup for hosted MySQL (no Render Shell)
│   ├── check_db.py           # Diagnose connection + list missing tables/columns
│   ├── create_admin.py       # The only supported way to create the first admin
│   └── reset_password.py     # Administrator-assisted password recovery
├── static/
│   ├── css/style.css         # Complete responsive design system
│   └── js/main.js            # Navigation, dropdown, previews, confirmations
├── templates/                # All Jinja2 pages and macros
├── uploads/                  # Validated item photos (git-ignored)
└── tests/
    ├── conftest.py           # Real-MySQL fixtures and factories
    ├── test_matching.py      # 14 algorithm tests (no database needed)
    └── test_app.py           # 26 end-to-end integration tests
```

---

## 4. Prerequisites

- **Python 3.10 or newer** — check with:
  ```powershell
  python --version
  ```
- **MySQL Server 8.x** installed and running.
- Windows PowerShell (commands below) or an equivalent terminal on macOS/Linux.
- No prior MySQL database is required; the setup scripts create it.

Check that MySQL is running:

```powershell
Get-Service *mysql*
```

---

## 5. Installation

Open PowerShell in the project folder:

```powershell
cd "C:\LOST AND FOUND\project"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux the activation command is `source .venv/bin/activate`.

> Always activate the virtual environment before running any project command.
> If `python` opens the Microsoft Store, install Python from python.org and tick
> **Add Python to PATH**.

---

## 6. MySQL setup

The application needs a MySQL account that can create and use two databases:

- `lost_and_found_plus` — the real application data.
- `lost_and_found_plus_test` — created automatically by the test suite.

### Option A — use the `root` account (simplest for a college demo)

Use your existing root password in `.env`. Nothing else is required.

### Option B — create a dedicated account (recommended)

Sign in to MySQL as root:

```powershell
mysql -u root -p
```

Run:

```sql
CREATE USER IF NOT EXISTS 'lfp_app'@'localhost'
  IDENTIFIED BY 'Use-A-Strong-Password-Here1';

GRANT ALL PRIVILEGES ON `lost_and_found_plus`.* TO 'lfp_app'@'localhost';
GRANT ALL PRIVILEGES ON `lost_and_found_plus_test`.* TO 'lfp_app'@'localhost';
FLUSH PRIVILEGES;
```

Then set `MYSQL_USER=lfp_app` and `MYSQL_PASSWORD=...` in `.env`.
The grant on a `database_name.*` pattern includes the `CREATE` privilege, so
`scripts/init_db.py` can create the database if it does not exist.

If your MySQL server is on a different port, set `MYSQL_PORT` accordingly.

---

## 7. Environment file

Copy the template and edit it:

```powershell
Copy-Item .env.example .env
notepad .env
```

Generate a strong secret key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

A filled-in `.env` looks like:

```dotenv
SECRET_KEY=replace-with-the-generated-64-character-hex-string
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD="your-mysql-password"
MYSQL_DATABASE=lost_and_found_plus
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=5242880
```

Notes:
- Quote passwords that contain `#`, spaces or quotes: `MYSQL_PASSWORD="my#pass"`.
- `.env` is listed in `.gitignore`. **Never commit it** and never paste real secrets into
  a report, screenshot or submission ZIP.
- Changing `SECRET_KEY` signs everyone out, because existing session cookies become invalid.

### Hosted MySQL (Aiven, Railway, etc.)

Local `MYSQL_HOST=localhost` only works on the same computer. A hosted web app such as
Render runs on a different machine, so it needs a hosted MySQL service. Set the values from
your provider's dashboard:

```dotenv
MYSQL_HOST=mysql-xxxxxxxx.aivencloud.com
MYSQL_PORT=12345
MYSQL_USER=avnadmin
MYSQL_PASSWORD=the-provider-password
MYSQL_DATABASE=defaultdb
MYSQL_SSL=true
MYSQL_SSL_VERIFY=false
```

Or paste the provider's single connection URL instead. It overrides the separate values:

```dotenv
MYSQL_URL=mysql://avnadmin:password@mysql-xxxxxxxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED
```

If the password contains `@`, `#`, `/` or `:`, URL-encode it (`@` becomes `%40`, `#` becomes
`%23`) when using `MYSQL_URL`. With separate values, quote the password normally.

Hosted MySQL providers usually require TLS. `MYSQL_SSL=true` encrypts the connection. For
certificate verification, download the provider's CA file and set
`MYSQL_SSL_CA=/path/to/ca.pem` and `MYSQL_SSL_VERIFY=true`. If you do not have the CA file,
`MYSQL_SSL_VERIFY=false` still encrypts traffic but does not verify the server certificate.

---

## 8. Create the database

```powershell
python scripts/init_db.py
```

Expected output:

```text
Schema applied (7 statements).
Database "lost_and_found_plus" is ready.
Existing data preserved: 0 user(s), 0 report(s).
```

`schema.sql` contains only `CREATE ... IF NOT EXISTS` statements. Re-running the command
**preserves existing users, reports, claims and matches**. It never drops a table or a row.

### Initialising a hosted database

The easiest option is the interactive script. It asks for the hosted host, port, user,
password and database; the password is hidden and is not saved:

```powershell
python scripts/init_remote.py
```

If you prefer to keep the values in a local secrets file, create `.env.render` (it is
git-ignored) with the same values as the deployed app:

```dotenv
MYSQL_URL=mysql://avnadmin:password@mysql-xxxxxxxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED
```

Then run:

```powershell
python scripts/init_remote.py --env-file .env.render
```

Alternatively, set temporary PowerShell environment variables and use the standard script:

```powershell
$env:MYSQL_HOST = "mysql-xxxxxxxx.aivencloud.com"
$env:MYSQL_PORT = "12345"
$env:MYSQL_USER = "avnadmin"
$env:MYSQL_PASSWORD = "the-provider-password"
$env:MYSQL_DATABASE = "defaultdb"
$env:MYSQL_SSL = "true"
python scripts/init_db.py
```

You can also run it from the Render **Shell** tab of the web service when your plan includes
Shell access (the environment variables are already present there):

```bash
python scripts/init_db.py
```

On Render, `AUTO_INIT_DB` is enabled automatically, so a missing schema is created when the
service next boots. The command above is still useful when you want to see the result
immediately. Check the result at any time with:

```powershell
python scripts/check_db.py
```

The script prints the target host, user and database (never the password), the MySQL version,
and any missing tables or columns.

Tables created:

| Table | Purpose |
|---|---|
| `users` | Members, staff and administrators (hashed passwords only) |
| `item_reports` | Lost/found reports, status, image filename, return flag |
| `claims` | Ownership claims with private verification details |
| `matches` | Persisted match pairs, score and explanation JSON |
| `notifications` | In-app match/claim notifications |

---

## 9. Create the first administrator

Registration **always** creates a normal `user`. This is deliberate: the first person to
register must never become an administrator by accident.

Run:

```powershell
python scripts/create_admin.py
```

You will be prompted for:

- administrator name,
- email address,
- password (minimum 8 characters, letters + numbers).

Non-interactive example (the password is still requested securely):

```powershell
python scripts/create_admin.py --name "Campus Administrator" --email admin@college.edu
```

To promote an existing account and reset its password:

```powershell
python scripts/create_admin.py --email admin@college.edu --promote-existing
```

For a hosted database, point the script at the same local secrets file used for setup:

```powershell
python scripts/create_admin.py --env-file .env.render
```

Sign in at `/login`; administrators are redirected to `/admin`.

---

## 10. Run the application

```powershell
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Useful URLs:

| Page | URL |
|---|---|
| Home | `/` |
| Browse | `/browse` |
| Register | `/register` |
| Login | `/login` |
| Member dashboard | `/dashboard` |
| Claims | `/claims` |
| Admin dashboard | `/admin` |
| Health check | `/health` |

If port `5000` is already in use, stop the other process or run on another port:

```powershell
python -m flask --app app run --port 5001
```

Stop the development server with `Ctrl+C`.

---

## 11. Run the automated tests

Make sure `.env` has the correct MySQL credentials and MySQL is running:

```powershell
python -m pytest -q
```

Expected result on a correctly configured machine:

```text
40 passed
```

What the suite covers:

- 14 pure algorithm tests (weighting, TF-IDF/cosine, missing data, category guard,
  thresholds, explanations, date compatibility).
- 26 integration tests against a **real MySQL** test database:
  - password hashing and duplicate-email rejection,
  - the critical "correct user name after logout/login" regression test,
  - dashboard isolation and ownership protection,
  - report validation and persistence,
  - smart-match creation,
  - full claim → approve → complete → returned workflow,
  - admin authorization and moderation,
  - match eligibility, duplicate prevention and recalculation,
  - image upload rejection/acceptance,
  - CSRF protection,
  - foreign-key cascades and the health endpoint.

Test database rules:
- The suite uses `lost_and_found_plus_test` by default.
- It **clears only that test database** before each integration test.
- `lost_and_found_plus` (your real data) is never touched.
- Override the test database name if needed:
  ```powershell
  $env:TEST_MYSQL_DATABASE = "my_custom_test_db"
  python -m pytest -q
  ```
- If MySQL is unavailable, the 14 algorithm tests still run and the 26 integration
  tests are skipped rather than falsely reported as passing.

---

## 12. How smart matching works

The scoring engine lives in `services/matching.py` and has no Flask or MySQL dependency.
`services/match_service.py` loads candidate reports, calls the engine, and persists results.

### Weights

| Factor | Weight | How it is compared |
|---|---:|---|
| Item name | 22% | Keyword/token overlap (with stop-word handling) |
| Category | 18% | Exact category match |
| Description | 16% | TF-IDF + cosine similarity |
| Brand / model | 10% | Token similarity |
| Distinctive marks | 10% | Token overlap |
| Location | 10% | Token overlap + campus proximity |
| Colour | 6% | Supporting evidence only |
| Date | 8% | Lost date must be compatible with found date |

### Important behaviour

- **Missing data never scores points.** If either report has no brand, the brand factor is
  skipped and the remaining weights are re-normalised. A missing detail cannot create a fake
  match.
- **Colour alone can never produce a strong score.** Even a perfect colour match carries only
  6% of the total.
- **Category guard:** when categories differ *and* the item names are barely related, the score
  is capped at 45%, so two unrelated reports that share generic words are not presented as a
  possible match.
- **Date compatibility:** a found item cannot meaningfully match a lost report dated long after
  it was found. Incompatible dates are treated as a conflict.
- **Eligibility:** returned/removed items are excluded from new matches. Items with
  `is_returned = 1` are never offered as candidates.
- **Duplicate prevention:** a `UNIQUE(lost_item_id, found_item_id)` constraint plus
  delete-then-recalculate logic means re-running the matcher cannot create duplicate rows.
- **Recalculation:** creating or editing a report deletes its old match rows, recalculates
  against eligible opposite-type reports, and recreates only matches at or above the minimum
  score (30%).
- **Explainability:** every stored match keeps its reasons, conflicts, missing factors and
  per-factor breakdown as JSON. The UI reads this to explain *why* a match was suggested.

### Score bands

| Score | Label shown |
|---:|---|
| 75–100 | Strong Possible Match |
| 55–74 | Possible Match |
| 35–54 | Weak Match |
| Below 30 | Not stored or shown |

A score is always presented as a **hint, not proof of ownership**. A human must verify the
claim before an item is handed over.

---

## 13. Claim and privacy workflow

1. A member opens a **Found** report and expands **Send a claim request**.
2. They write a message and a private detail only the true owner would know.
3. The claim is stored with status `Pending`.
4. The finder or an administrator reviews it.
5. On approval:
   - the claim becomes `Approved`,
   - the claimant can see the finder's contact details,
   - the item status becomes `Matched`.
6. Only after the physical handover does the finder/admin mark it `Completed`.
7. The item becomes `Returned`, `is_returned = 1`, and remaining pending claims are rejected.

Server-side rules:

- You cannot claim your own found report.
- You cannot create a second active claim for the same item.
- You cannot claim a returned/removed item.
- Contact details are hidden from anonymous visitors and from members without an approved claim.
- Claims can be reviewed only by the item owner or an administrator.
- Only an approved claim can be completed.
- Completed claims cannot be changed.

---

## 14. Security notes

- **Sessions store only the database user ID.** The user record is reloaded from MySQL on every
  request, so one member can never inherit another member's name, role or data.
- `session.clear()` is called on login and logout to prevent session fixation and data leakage.
- **Every SQL query is parameterised** with `%s` placeholders; no user input is concatenated
  into SQL.
- **CSRF protection** is applied to every `POST` request using a per-session token and a
  constant-time comparison.
- **Passwords are hashed** with Werkzeug (PBKDF2-SHA256); plaintext passwords are never stored.
- **Uploads** are limited to 5 MB, restricted to JPG/PNG/GIF/WEBP, verified with Pillow instead
  of trusting the filename, stored under random names, and served through
  `send_from_directory` with `os.path.basename`.
- **Ownership checks run on the server** for editing, deleting, reviewing and completing.
  Hiding a button in HTML is never treated as security.
- **Admin routes** are protected by `@admin_required`; a normal member receives `403`.
- **Contact details** are resolved server-side from the database and only rendered when the
  viewer is the owner, an administrator, or a claimant with an approved/completed claim.
- **Debug mode is for local development only.** Never expose the Flask development server to a
  network or the internet.
- **No secrets live in source code.** `SECRET_KEY` and MySQL credentials come from `.env`.
- The unique pair constraint and workflow checks enforce business rules in the database as well
  as in the routes.

---

## 15. Password recovery

There is intentionally no public "reset by email" endpoint, because this project has no mail
server and a weak reset flow would be a security risk.

An administrator with server access runs:

```powershell
python scripts/reset_password.py
```

Then enters the member's email and a new password twice. The password is hashed before it is
stored. The member signs in with the new password immediately.

A signed-in member can also change their own password from **Profile → Password**.

---

## 16. Troubleshooting

| Problem | Fix |
|---|---|
| `Access denied for user ... (1045)` | The password in `.env` is wrong. Quote passwords containing `#` or spaces. |
| `Can't connect to MySQL server ... (2003)` | MySQL is not running or `MYSQL_PORT` is wrong. Start the MySQL service, or check the hosted provider's host/port. |
| `Unknown database 'lost_and_found_plus'` | Run `python scripts/init_db.py`. On shared hosting, create the database in the provider dashboard first if the account cannot create databases. |
| `Table '...' doesn't exist` | The database is reachable but the schema is missing. Run `python scripts/init_db.py`; it is safe to re-run. |
| `Table 'defaultdb.item_reports' doesn't exist` on Aiven | The connection is correct, but `schema.sql` was never applied to Aiven's `defaultdb`. Run `python scripts/init_remote.py` from your PC, or use the no-Shell Start Command method in [Deployment notes](#17-deployment-notes). In the Aiven Query Editor, select `defaultdb` and run only the `CREATE TABLE` statements (do **not** run the `CREATE DATABASE lost_and_found_plus` or `USE lost_and_found_plus` lines). |
| Home page shows "database could not connect", but `/health` returns `database: connected` | This is a **schema** problem, not a password problem. `/health` reports `schema: incomplete` and the missing tables. Run `python scripts/init_remote.py`, or redeploy the updated app so auto-init creates the tables. |
| `/health` returns `schema: incomplete` | The app can reach MySQL but required tables/columns are missing or outdated. Run `python scripts/init_remote.py` against the hosted database, or redeploy the updated app and restart it. |
| Deployed app still uses `localhost` | A hosted app cannot reach your PC's MySQL. Set `MYSQL_HOST`/`MYSQL_PORT` (or `MYSQL_URL`) to a hosted database in the hosting dashboard, then redeploy. |
| SSL/TLS handshake error on a hosted database | Set `MYSQL_SSL=true` (or add `?ssl-mode=REQUIRED` to `MYSQL_URL`). For certificate verification, set `MYSQL_SSL_CA` and `MYSQL_SSL_VERIFY=true`. |
| Changed environment variables but the app still fails | Redeploy or restart the service. Most hosts only read environment variables at process start. |
| `ModuleNotFoundError: No module named 'flask'` | The virtual environment is not active, or dependencies are not installed. Run `.\.venv\Scripts\Activate.ps1` and `pip install -r requirements.txt`. |
| PowerShell refuses to activate the venv | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `Port 5000 is already in use` | Stop the other server or run `python -m flask --app app run --port 5001`. |
| Upload returns "too large" | Maximum size is 5 MB (`MAX_CONTENT_LENGTH`). |
| Uploaded image does not appear | Check that the `uploads/` folder exists and is writable. The app recreates it at startup. |
| Everyone is signed out after a restart | `SECRET_KEY` changed. Use one stable value in `.env`. |
| Integration tests are skipped | MySQL is unavailable or `.env` credentials are wrong. Algorithm tests still run. |
| `caching_sha2_password` / authentication error | `mysql-connector-python` supports MySQL 8 authentication. Make sure you installed `requirements.txt` with the project's Python, and that the account's plugin is `caching_sha2_password` (the MySQL 8 default). |
| Admin page returns `403` | The signed-in account's `role` is not `admin`. Use `python scripts/create_admin.py`. |
| The first registered user is not an admin | This is intentional. Use the admin script. |

Check database connectivity and schema readiness without starting the UI:

```powershell
python scripts/check_db.py
```

To repair a missing schema in the same command:

```powershell
python scripts/check_db.py --init
```

The web app also exposes a read-only health check:

```text
GET /health
```

`200` with `"schema": "ready"` means the database and tables are ready.
`503` with `"schema": "incomplete"` means MySQL is reachable but the schema
setup must be run (`python scripts/init_remote.py`) or the updated app must be
redeployed so its automatic boot initialiser can create the tables.

---

## 17. Deployment notes

A short copy-paste checklist for GitHub + Render is in [DEPLOY.md](DEPLOY.md).

### Local demonstration (recommended for a college viva)

```powershell
python app.py
```

This uses Flask's development server with auto-reload. It is fine on `127.0.0.1` for a demo,
but not for a public server.

### Render + free hosted MySQL (Aiven)

A Render web service **cannot reach MySQL running on your laptop**. `localhost` inside Render
means the Render container itself. This is the most common cause of the “database could not be
reached” page on a deployed copy.

The free option below uses [Aiven for MySQL](https://aiven.io/free-mysql-database) (1 GB free,
no card required). Railway, Clever Cloud or any other MySQL provider also works; only the
host/port/user/password/database values change.

1. **Create the database**
   - Sign in at <https://console.aiven.io/> and create a **MySQL** service on the free plan.
   - Open the service **Overview** and copy the **Host**, **Port**, **User** and **Password**.
   - Use `defaultdb` as the database name, or create `lost_and_found_plus` in the Aiven
     console. Aiven requires TLS.
2. **Add Render environment variables**
   - Open your Render service → **Environment** → **Add Environment Variable**.
   - Add these values (use the real ones from Aiven):

     | Key | Example value |
     |---|---|
     | `SECRET_KEY` | a fresh 64-character hex string |
     | `MYSQL_HOST` | `mysql-xxxxxxxx.aivencloud.com` |
     | `MYSQL_PORT` | `12345` |
     | `MYSQL_USER` | `avnadmin` |
     | `MYSQL_PASSWORD` | the Aiven password |
     | `MYSQL_DATABASE` | `defaultdb` (or `lost_and_found_plus`) |
     | `MYSQL_SSL` | `true` |
     | `MYSQL_SSL_VERIFY` | `false` (or `true` with `MYSQL_SSL_CA`) |
     | `FLASK_ENV` | `production` |

     Do **not** put `MYSQL_HOST=localhost` in Render. Do not rely on uploading `.env`; `.env`
     is deliberately excluded from Git. The Render dashboard is the source of truth for
     deployed secrets.
   - If your provider gives one `mysql://...` URL, you may set `MYSQL_URL` instead of the
     separate `MYSQL_*` values. It takes priority.
3. **Deploy / redeploy**
   - Render start command (either is fine):

     ```text
     waitress-serve --listen=0.0.0.0:$PORT app:app
     ```

     or, if your service is already using Gunicorn:

     ```text
     gunicorn --bind 0.0.0.0:$PORT app:app
     ```

     `--bind 0.0.0.0:$PORT` is important on Render: it makes Gunicorn listen on
     the public interface and on the port Render assigns. If your existing
     service already works with a different Gunicorn command, keep that command.

   - On Render, `AUTO_INIT_DB` defaults to true. The first boot creates any missing tables
     using `schema.sql`. It never drops existing data. You can also set `AUTO_INIT_DB=1`
     explicitly, then remove it later if you prefer.
4. **If your Render plan has no Shell access**
   You can run the schema setup from the Start Command instead; changing the Start Command
   does not require a paid Shell.

   - Copy your existing Start Command (for example
     `gunicorn --bind 0.0.0.0:$PORT app:app`).
   - Temporarily prepend this one-time initialiser, keeping the semicolon so the web server
     still starts even if the database setup reports an error:

     ```bash
     python -c "import db; from app import create_app; a=create_app(); ctx=a.app_context(); ctx.push(); conn=db._connect(); cur=conn.cursor(); stmts=db._split_statements(open('schema.sql', encoding='utf-8').read()); [cur.execute(s) for s in stmts if not s.strip().upper().startswith(('CREATE DATABASE', 'USE '))]; conn.commit(); cur.close(); conn.close(); print('schema ready'); ctx.pop()" ; gunicorn --bind 0.0.0.0:$PORT app:app
     ```

     Replace the final `gunicorn --bind 0.0.0.0:$PORT app:app` with your own existing
     Start Command if it is different.

   - Save the setting and let Render restart the service.
   - In the Render logs, look for `schema ready`.
   - Refresh the site, then remove the long initialiser and restore your normal Start Command.
     The initialiser is safe to leave in place, but removing it keeps future boots fast.

5. **Verify**
   - Open `https://<your-service>.onrender.com/health`.
   - Expected result:

     ```json
     {"database":"connected","schema":"ready","status":"ok"}
     ```

   - If it returns `"schema":"incomplete"`, run one of the setups in step 4 again, or run
     `python scripts/init_remote.py` locally with the hosted connection values.
6. **Create an administrator on the hosted database**
   - Run it from your computer with the hosted values:

     ```powershell
     python scripts/create_admin.py --env-file .env.render
     ```

   - If your plan includes Render Shell, you can also run `python scripts/create_admin.py`
     there.
7. **Optional: copy your local demo data**

   ```powershell
   mysqldump -u root -p --databases lost_and_found_plus > backup.sql
   mysql -h <host> -P <port> -u <user> -p < backup.sql
   ```

   Use the hosted database name in the dump/import if it is not `lost_and_found_plus`.

Notes:
- Render free web services sleep after inactivity. The first request after sleep can take a
  few seconds; Aiven free services can also be powered off after long inactivity and can be
  restarted from the Aiven console.
- Uploaded images are stored on Render's ephemeral filesystem and disappear after a redeploy
  or restart. For a viva demo, upload images after the final deploy. For persistence, mount a
  Render Disk (paid) at `/var/data` and set `UPLOAD_FOLDER=/var/data/uploads`, or use object
  storage such as S3/Cloudinary.
- Keep `FLASK_ENV=production` on Render. It turns off debug mode and marks session cookies
  `Secure` (Render serves HTTPS). Do not expose the Flask development server publicly.

### Windows server / LAN demo with Waitress

`waitress` is included in `requirements.txt`.

```powershell
$env:FLASK_ENV = "production"
waitress-serve --listen=0.0.0.0:8000 app:app
```

Open `http://<server-ip>:8000`.

Production notes:
- `ProductionConfig` sets `SESSION_COOKIE_SECURE = True`, which requires HTTPS. If you test
  over plain HTTP on a LAN, use `FLASK_ENV=development` or place the app behind an HTTPS
  reverse proxy (Caddy, nginx, IIS ARR).
- Put a reverse proxy in front of Waitress for TLS, compression and request limits.
- Use a dedicated MySQL account with a strong password and grant only the two required
  databases.
- Keep `.env` outside version control and restrict file permissions.
- Back up `lost_and_found_plus` and the `uploads/` folder together:
  ```powershell
  mysqldump -u root -p --databases lost_and_found_plus > backup.sql
  ```
- Run `python -m pytest -q` after deployment configuration changes.
- Never run the Flask development server with `debug=True` on a public interface.

---

## 18. Data-safety rules

- `schema.sql` never contains `DROP DATABASE`, `DROP TABLE`, `TRUNCATE` or destructive
  `ALTER` statements.
- `scripts/init_db.py` only creates what is missing and reports how many existing users and
  reports were preserved.
- Integration tests use a separate `lost_and_found_plus_test` database and clear only that
  database.
- Deleting a user cascades to that user's reports, claims, matches and notifications by
  database design. The admin UI warns before deletion.
- Returned items are kept for records and cannot be deleted or edited by members.

---

## Quick command summary

```powershell
cd "C:\LOST AND FOUND\project"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
# edit .env with your MySQL password and a generated SECRET_KEY

python scripts/init_db.py
python scripts/check_db.py
python scripts/create_admin.py
python app.py

# in a second terminal, with the venv active:
python -m pytest -q
```
