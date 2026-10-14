PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id         INTEGER NOT NULL UNIQUE,
    username            TEXT,
    name                TEXT    NOT NULL,
    email               TEXT    NOT NULL UNIQUE,
    gender              TEXT CHECK (gender IN ('m', 'f')),
    show_username       INTEGER NOT NULL DEFAULT 1,
    rating_sum          INTEGER NOT NULL DEFAULT 0,
    rating_count        INTEGER NOT NULL DEFAULT 0,
    trips_count         INTEGER NOT NULL DEFAULT 0,
    is_banned           INTEGER NOT NULL DEFAULT 0,
    low_rating_notified INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL
);

-- status: open (1 участник, ждёт) | formed (2-4) | completed | cancelled
CREATE TABLE IF NOT EXISTS groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    direction    TEXT    NOT NULL,
    district     TEXT    NOT NULL,
    date         TEXT    NOT NULL,
    time         TEXT    NOT NULL,
    women_only   INTEGER NOT NULL DEFAULT 0,
    window_min   INTEGER NOT NULL DEFAULT 15,
    organizer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status       TEXT    NOT NULL DEFAULT 'open',
    total_price  INTEGER,
    price_asked  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);

-- status: waiting (один в группе) | matched | completed | cancelled | expired
CREATE TABLE IF NOT EXISTS trips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    direction   TEXT    NOT NULL,
    district    TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    time        TEXT    NOT NULL,
    women_only  INTEGER NOT NULL DEFAULT 0,
    window_min  INTEGER NOT NULL DEFAULT 15,
    status      TEXT    NOT NULL DEFAULT 'waiting',
    group_id    INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    confirmed   INTEGER,
    reminded_30 INTEGER NOT NULL DEFAULT 0,
    reminded_15 INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

-- status: pending | marked_paid | confirmed
CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id         INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount           INTEGER NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'pending',
    overdue_notified INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    UNIQUE (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS ratings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    from_user      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    to_user        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    score          INTEGER CHECK (score BETWEEN 1 AND 5),
    complaint_text TEXT,
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS email_codes (
    email      TEXT PRIMARY KEY,
    code_hash  TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    sent_at    TEXT    NOT NULL
);

-- События для аналитики эксперимента. user_id без внешнего ключа:
-- после /delete_me он заменяется на отрицательное значение (обезличивание).
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT    NOT NULL,
    user_id    INTEGER,
    ref_id     INTEGER,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trips_user ON trips(user_id, status);
CREATE INDEX IF NOT EXISTS idx_trips_group ON trips(group_id);
CREATE INDEX IF NOT EXISTS idx_groups_match ON groups(direction, district, date, status);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, status);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
