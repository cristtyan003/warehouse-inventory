# Warehouse Inventory

A small internal web portal for warehouse safety teams. It tracks PPE stock month by month, schedules safety observation routines, handles uniform and PPE requests, and has a simple role-based user area. Built with Flask, SQLAlchemy and a single-page dashboard (vanilla JS, no build step).

## Features

- **PPE stock**: monthly stock, outflow, purchases and cleaning costs per item, targets, budget, a consolidated view and coverage insights
- **Safety routines**: schedule BBS / DSW observations per manager and shift, mark them done
- **Uniform / PPE requests**: managers submit requests, editors deliver or refuse them with a justification
- **Support**: configurable support contact
- **Users & access**: four roles, account blocking, password resets, manager tracking
- **Live sync**: open sessions pick up other people's changes within seconds
- Light and dark theme, responsive layout

## Roles

| Role | Can do |
| --- | --- |
| Viewer | Read the stock dashboards |
| Manager | Everything a viewer can, plus schedule routines and request uniforms |
| Editor | Edit stock, catalog and prices; deliver or refuse requests; see manager tracking |
| Admin | Everything an editor can, plus manage users and access |

New self-registered accounts start as viewers.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_EMAIL=admin@example.com
export ADMIN_PASSWORD='choose-a-strong-password'

python app.py
```

Open http://127.0.0.1:5000 and sign in with the admin account above. The catalog starts empty; load the sample one with `python seed.py` (see below) or add items from the UI. `ADMIN_EMAIL` / `ADMIN_PASSWORD` are only used to create the first account when the database has no users.

### Demo data

To load a sample catalog (57 fictional items) and four demo accounts:

```bash
export DEMO_PASSWORD='something-you-pick'
python seed.py
```

This creates `admin@example.com`, `editor@example.com`, `manager@example.com` and `viewer@example.com`, all with `DEMO_PASSWORD`. The seed only fills empty tables, so running it twice is safe. Do not use it in a real deployment.

### Windows shortcut

Double-click `run.bat`. It creates a virtual environment, installs the dependencies, loads the demo data and starts the server at http://127.0.0.1:5000. It is meant for local testing only.

## Configuration

All settings are environment variables. `.env.example` lists them; the app does not read `.env` by itself, so export the values or load them with your process manager.

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | random per start | Session signing key. Set a fixed value in production or everyone is signed out on restart |
| `DATABASE_URL` | `sqlite:///warehouse.db` | SQLAlchemy connection string |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | unset | First admin, created only when no user exists |
| `DEMO_PASSWORD` | unset | Password for demo accounts created by `seed.py` |
| `SUPPORT_EMAIL` | `support@example.com` | Default support contact (editable in the UI) |
| `ALLOW_REGISTRATION` | `1` | Set to `0` to disable self-registration |
| `ALLOWED_EMAIL_DOMAINS` | `*` | Comma-separated domains allowed to register, or `*` for any |
| `REGISTRATION_CODE` | unset | If set, sign-up requires this access code |
| `REFERENCE_MONTH` | `2026-09` | Month whose opening stock is the baseline |
| `FLASK_DEBUG`, `HOST`, `PORT` | `0`, `127.0.0.1`, `5000` | Development server options |

## Running in production

The built-in server is for development. Use a WSGI server behind a reverse proxy with HTTPS:

```bash
pip install gunicorn
gunicorn -w 4 -b 127.0.0.1:8080 app:app
```

Checklist:

- set a fixed `SECRET_KEY`
- serve over HTTPS and keep the app behind your network or a VPN if it is internal
- set `ALLOW_REGISTRATION=0` or restrict `ALLOWED_EMAIL_DOMAINS` / `REGISTRATION_CODE`
- back up the database regularly

## Backups

```bash
python backup_db.py        # keeps the 30 latest copies in ./backups
python backup_db.py 10     # keep 10
```

Set `DB_PATH` if the database file is not `warehouse.db` next to the script. The script uses SQLite's online backup API, so it is safe while the app is running. Schedule it with cron or Task Scheduler.

## Tests

```bash
python run_tests.py
```

Each file in `tests/` runs against a temporary database and does not touch your data.

## Project layout

```
app.py            routes, auth, validation
models.py         SQLAlchemy models and roles
seed.py           demo catalog and accounts
seed_data.py      fictional sample items and prices
backup_db.py      SQLite backup helper
templates/        dashboard, login, register
static/           login page assets
tests/            test suite
```

## License

Add the license of your choice before publishing.
