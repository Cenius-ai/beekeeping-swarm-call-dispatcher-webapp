-- Beekeeping Swarm Call Dispatcher — canonical schema.
-- Executed idempotently on the boot path (db.init_db) and by seed.py.
-- SQLite only: no extensions, no network, relative file database.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    display_name  TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS volunteer (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL,
    phone              TEXT    NOT NULL,
    lat                REAL    NOT NULL,
    lon                REAL    NOT NULL,
    coverage_radius_km REAL    NOT NULL CHECK (coverage_radius_km > 0 AND coverage_radius_km <= 50),
    skills             TEXT    NOT NULL DEFAULT '',
    is_available       INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1)),
    updated_at         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS swarm_report (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL,
    logged_by_user_id   INTEGER NOT NULL REFERENCES user(id),
    caller_name         TEXT    NOT NULL,
    caller_phone        TEXT    NOT NULL,
    site_name           TEXT    NOT NULL,
    lat                 REAL    NOT NULL,
    lon                 REAL    NOT NULL,
    cluster_size_bucket TEXT    NOT NULL,
    urgency             TEXT    NOT NULL,
    notes               TEXT    NOT NULL DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'assigned', 'collected', 'rehomed', 'lost', 'not_found'))
);

CREATE TABLE IF NOT EXISTS dispatch (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id            INTEGER NOT NULL REFERENCES swarm_report(id) ON DELETE CASCADE,
    volunteer_id         INTEGER NOT NULL REFERENCES volunteer(id),
    state                TEXT    NOT NULL
        CHECK (state IN ('confirmed', 'declined', 'cancelled', 'reassigned', 'completed')),
    distance_km          REAL    NOT NULL,
    confirmed_by_user_id INTEGER NOT NULL REFERENCES user(id),
    created_at           TEXT    NOT NULL,
    closed_at            TEXT,
    close_reason         TEXT
);

-- At most one ACTIVE dispatch per report (service layer enforces it too).
CREATE UNIQUE INDEX IF NOT EXISTS ux_dispatch_active_per_report
    ON dispatch (report_id) WHERE state = 'confirmed';

CREATE TABLE IF NOT EXISTS outcome (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id            INTEGER NOT NULL REFERENCES swarm_report(id) ON DELETE CASCADE,
    dispatch_id          INTEGER REFERENCES dispatch(id),
    recorded_by_user_id  INTEGER NOT NULL REFERENCES user(id),
    recorded_at          TEXT    NOT NULL,
    actual_cluster_size  INTEGER,
    hive_box             TEXT    NOT NULL DEFAULT '',
    rehomed_to           TEXT    NOT NULL DEFAULT '',
    result               TEXT    NOT NULL
        CHECK (result IN ('collected', 'rehomed', 'lost', 'not_found')),
    notes                TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_dispatch_report        ON dispatch (report_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_volunteer     ON dispatch (volunteer_id);
CREATE INDEX IF NOT EXISTS ix_dispatch_state         ON dispatch (state);
CREATE INDEX IF NOT EXISTS ix_outcome_report         ON outcome (report_id);
CREATE INDEX IF NOT EXISTS ix_outcome_result         ON outcome (result);
CREATE INDEX IF NOT EXISTS ix_report_status          ON swarm_report (status);
CREATE INDEX IF NOT EXISTS ix_report_created         ON swarm_report (created_at);
CREATE INDEX IF NOT EXISTS ix_report_logged_by       ON swarm_report (logged_by_user_id);
