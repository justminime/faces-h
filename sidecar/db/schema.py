"""SQLite DDL constants for faces-h. Tables are created with IF NOT EXISTS so
this module is idempotent — safe to call on every startup."""

PHOTOS = """
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT    NOT NULL UNIQUE,
    mtime       INTEGER NOT NULL,
    scanned_at  INTEGER,
    width       INTEGER,
    height      INTEGER,
    taken_at    INTEGER
)
"""

FACES = """
CREATE TABLE IF NOT EXISTS faces (
    id                  INTEGER PRIMARY KEY,
    photo_id            INTEGER NOT NULL REFERENCES photos(id),
    bbox_x              REAL,
    bbox_y              REAL,
    bbox_w              REAL,
    bbox_h              REAL,
    detection_conf      REAL    NOT NULL,
    embedding           BLOB,
    embedding_id        INTEGER,
    person_id           INTEGER REFERENCES people(id),
    suggested_person_id INTEGER REFERENCES people(id),
    assign_conf         REAL,
    assign_status       TEXT    NOT NULL
)
"""

PEOPLE = """
CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    created_at  INTEGER NOT NULL,
    centroid    BLOB
)
"""

CORRECTIONS = """
CREATE TABLE IF NOT EXISTS corrections (
    id              INTEGER PRIMARY KEY,
    face_id         INTEGER NOT NULL REFERENCES faces(id),
    old_person_id   INTEGER,
    new_person_id   INTEGER,
    corrected_at    INTEGER NOT NULL
)
"""

SCAN_STATE = """
CREATE TABLE IF NOT EXISTS scan_state (
    key     TEXT PRIMARY KEY,
    value   TEXT
)
"""

SCAN_ROOTS = """
CREATE TABLE IF NOT EXISTS scan_roots (
    id           INTEGER PRIMARY KEY,
    path         TEXT    NOT NULL UNIQUE,
    added_at     INTEGER NOT NULL,
    is_network   INTEGER NOT NULL DEFAULT 0,
    last_seen_at INTEGER
)
"""

# Migration: add columns introduced after initial schema deployment.
# SQLite raises OperationalError if the column already exists; we swallow it.
SCAN_ROOTS_MIGRATIONS = [
    "ALTER TABLE scan_roots ADD COLUMN is_network   INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE scan_roots ADD COLUMN last_seen_at INTEGER",
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_faces_photo     ON faces(photo_id)",
    "CREATE INDEX IF NOT EXISTS idx_faces_person    ON faces(person_id)",
    "CREATE INDEX IF NOT EXISTS idx_faces_status    ON faces(assign_status)",
    "CREATE INDEX IF NOT EXISTS idx_photos_path     ON photos(path)",
    "CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photos(taken_at)",
    "CREATE INDEX IF NOT EXISTS idx_scan_roots_path ON scan_roots(path)",
]

ALL_TABLES = [PHOTOS, FACES, PEOPLE, CORRECTIONS, SCAN_STATE, SCAN_ROOTS]
ALL_MIGRATIONS = SCAN_ROOTS_MIGRATIONS
