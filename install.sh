#!/usr/bin/env bash
#
# Beekeeping Swarm Call Dispatcher — one-command setup.
#
# Installs the project's Python dependencies, creates the embedded SQLite
# database, seeds the demo data and verifies the app imports. It installs
# nothing at the system level and it never starts the web server: run
# `python3 app.py` afterwards.
#
#     bash install.sh
#
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Installing Python dependencies (project-level only)"
python3 -m pip install --upgrade pip setuptools wheel --quiet
python3 -m pip install -r requirements.txt --quiet

if [ ! -f .env ]; then
  echo "==> Writing .env with a freshly generated session secret"
  {
    printf 'SECRET_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    printf 'DATABASE_URL=sqlite:///./data.db\n'
  } > .env
else
  echo "==> Keeping the existing .env"
fi

echo "==> Creating the schema and seeding demo data (idempotent)"
python3 -m seed

echo "==> Verifying the application imports"
python3 -c "import app; print('   app imports cleanly; database ready')"

cat <<'EOF'

Setup complete - no server was started.

  Start the dispatcher:   python3 app.py     (http://0.0.0.0:8050)
  Run the test suite:     python3 -m pytest
  Demo sign-in:           see README.md -> "## Demo accounts"

EOF
