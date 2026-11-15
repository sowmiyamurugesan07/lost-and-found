# Deploy Lost & Found+ to Render

This is the short deployment checklist. The full setup, security notes and
troubleshooting guide are in [README.md](README.md).

The prepared ZIP is **`lost-and-found-plus-deploy.zip`** (one folder above this
project). It contains the complete application, its test suite and the database
schema, but **not** `.env`, uploaded photos or Python caches.

---

## 1. Upload the code to GitHub

1. Extract `lost-and-found-plus-deploy.zip`.
2. Open your GitHub repository in a browser.
3. Choose **Add file → Upload files**.
4. Drag the **contents** of the extracted project folder into the upload area
   (not the folder itself). GitHub keeps the folder structure.
   In File Explorer, enable **View → Hidden items** first so `.env.example` and
   `.gitignore` are included.
5. Commit the changes.

If you use GitHub Desktop instead, copy the extracted files into your local
clone, then commit and push.

---

## 2. Check the Render service settings

Open your Render web service → **Settings**:

| Setting | Value |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn --bind 0.0.0.0:$PORT app:app` |
| Health Check Path | `/health` |

If your existing service already runs with a different working Start Command,
keep it. The important part is that Gunicorn listens on `0.0.0.0` and `$PORT`.

---

## 3. Environment variables

Open **Environment** and make sure these are present. Use the values from your
Aiven MySQL service; never use `localhost` on Render.

| Key | Value |
|---|---|
| `SECRET_KEY` | A long random string (see below) |
| `FLASK_ENV` | `production` |
| `MYSQL_HOST` | Aiven host, for example `mysql-xxxx.aivencloud.com` |
| `MYSQL_PORT` | Aiven port, for example `12345` |
| `MYSQL_USER` | Aiven user, usually `avnadmin` |
| `MYSQL_PASSWORD` | Aiven password |
| `MYSQL_DATABASE` | `defaultdb` (or your chosen database) |
| `MYSQL_SSL` | `true` |
| `MYSQL_SSL_VERIFY` | `false` (or `true` with `MYSQL_SSL_CA`) |
| `AUTO_INIT_DB` | `true` (already the default on Render) |

Generate a secret key locally:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Do not commit `.env` or paste the database password into GitHub. The Render
dashboard is the source of truth for deployed secrets. If your repository
already contains a `.env` file from an earlier upload, delete it from GitHub
and rotate the exposed database password and `SECRET_KEY`.

You may use one `MYSQL_URL` instead of the separate `MYSQL_*` values:

```text
mysql://avnadmin:password@host:port/defaultdb?ssl-mode=REQUIRED
```

`MYSQL_URL` takes priority when present.

---

## 4. Deploy

Click **Manual Deploy → Deploy latest commit** (or wait for the GitHub push to
trigger a deploy).

On the first boot, the updated app automatically creates any missing tables in
the configured database. The schema file only uses `CREATE ... IF NOT EXISTS`,
so existing users, reports, claims and matches are never dropped.

Watch the Render log for:

```text
Database schema ready for "defaultdb" (7 statements checked).
```

Then open:

```text
https://YOUR-SERVICE.onrender.com/health
```

Expected result:

```json
{"database":"connected","schema":"ready","status":"ok"}
```

If you see `"schema":"incomplete"`, read the `missing_tables` list and see
[README.md → Troubleshooting](README.md#16-troubleshooting).

---

## 5. Create the first administrator

Registration always creates a normal member. Create the administrator from
your PC with the hosted connection values:

```powershell
cd "C:\LOST AND FOUND\project"
python scripts/create_admin.py --env-file .env.render
```

The `.env.render` file is local and git-ignored. It can contain the same
`MYSQL_URL` or `MYSQL_*` values as Render. See
[README.md → Create the first administrator](README.md#9-create-the-first-administrator).

Alternatively, register on the site and promote that account:

```powershell
python scripts/create_admin.py --env-file .env.render --email you@example.com --promote-existing
```

---

## 6. Final checks

- Sign in as the administrator at `/login` and open `/admin`.
- Report one lost item and one found item; check that a match appears.
- Submit a claim; verify that contact details stay hidden until approval.
- Upload a test image, then remember that Render's free filesystem is
  **ephemeral**: uploaded photos disappear after a restart/redeploy. For a
  permanent deployment, mount a Render Disk or use object storage.
- Keep `FLASK_ENV=production` so debug mode is off and session cookies are
  marked `Secure`.

---

## No-Shell database repair

If the live site is still running older code and reports
`Table 'defaultdb.item_reports' doesn't exist`, use the no-Shell Start Command
method in [README.md → Deployment notes](README.md#17-deployment-notes). You do
not need a paid Render Shell.

The local alternative is:

```powershell
python scripts/init_remote.py
```

It asks for the hosted MySQL values, applies the schema and never drops data.
