# Install and run

Everything below runs as an unprivileged user. No system packages are installed —
only the project's own Python dependencies.

## System prerequisites

Provide these yourself; `install.sh` never installs them.

- **Python 3.11 or newer** (`python3 --version`)
- **pip** for that interpreter (`python3 -m pip --version`)
- A working C toolchain is *not* required: every dependency ships wheels for
  Python 3.11 on Linux.

SQLite is compiled into CPython, so no database server is needed.

## 1. Install the dependencies

```bash
bash install.sh
```

The script:

1. upgrades `pip`/`setuptools`/`wheel`,
2. installs `requirements.txt` at the project root,
3. writes a `.env` with a freshly generated `SECRET_KEY` (kept if it already exists),
4. runs the idempotent seed,
5. imports the app once as a self-check,

then **exits without starting the server**. Re-running it is safe.

## 2. Seed the demo data

Already done by `install.sh`. To re-run it on its own:

```bash
python3 -m seed
```

The seed is idempotent (check-before-insert): 1 coordinator, 12 collectors
(10 available), 60 swarm reports spread across all six statuses, 46 dispatch
rows and 27 outcomes. Running it twice changes no row counts.

## 3. Run in development

```bash
python3 app.py
```

The server binds `0.0.0.0:8050` and prints the address it is listening on.
Change the port with the environment:

```bash
PORT=9000 python3 app.py
```

Flask's own CLI works too — `.flaskenv` (loaded by `python-dotenv`) points it at
this module and binds `0.0.0.0:5000`, so there is exactly one discoverable
application:

```bash
python3 -m flask run
```

Open <http://localhost:8050> (or <http://localhost:5000> for `flask run`). `/`
redirects to the sign-in screen; sign in with the demo credentials from the
README.

## 4. Run the tests

```bash
python3 -m pytest -q
```

## Environment variables

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | `cenius-dev-…` development key | Written to `.env` by `install.sh`. Used to sign the session cookie. |
| `DATABASE_URL` | `sqlite:///./data.db` | Any SQLAlchemy URL. The default relative SQLite file is created, migrated and seeded on boot. |
| `PORT` | `8050` | Port for `python3 app.py`. |
| `FLASK_RUN_HOST` / `FLASK_RUN_PORT` | `0.0.0.0` / `5000` | Set in `.flaskenv` for `flask run`. |

No `.env` file is required. `cp .env.example .env` followed by `python3 app.py`
boots with zero edits, and so does starting with no `.env` at all.

## Deploying behind a WSGI server

The Dash app exposes `server = app.server` (a Flask app). Importing `app` also
creates and seeds the database, so a WSGI launcher needs no separate migrate
step:

```bash
gunicorn --bind 0.0.0.0:8050 app:server
```

Keep the session cookie over plain HTTP for local/preview runs: the app leaves
`SESSION_COOKIE_SECURE` off on purpose so sign-in works without TLS.
