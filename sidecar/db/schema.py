"""SQLite DDL constants for faces-h. Tables are created with IF NOT EXISTS so
this module is idempotent — safe to call on every startup."""

PHOTOS = """
CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY,
    path            TEXT    NOT NULL UNIQUE,
    mtime           INTEGER NOT NULL,
    scanned_at      INTEGER,
    width           INTEGER,
    height          INTEGER,
    taken_at        INTEGER,
    faces_extracted INTEGER NOT NULL DEFAULT 0,
    missing         INTEGER NOT NULL DEFAULT 0,
    blur_score      REAL,
    file_size       INTEGER,
    phash           INTEGER,
    content_hash    TEXT,
    exif_orientation INTEGER,
    suggested_rotation INTEGER,
    rotation_checked INTEGER NOT NULL DEFAULT 0
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

# Migrations: add columns introduced after initial schema deployment.
# Each entry is (alter_stmt, one_shot_followup_or_None). SQLite raises
# OperationalError from the ALTER if the column already exists; the caller
# swallows that and MUST also skip the followup — followups run exactly once,
# on the connection that actually added the column.
SCAN_ROOTS_MIGRATIONS: list[tuple[str, str | None]] = [
    ("ALTER TABLE scan_roots ADD COLUMN is_network   INTEGER NOT NULL DEFAULT 0", None),
    ("ALTER TABLE scan_roots ADD COLUMN last_seen_at INTEGER", None),
]

# faces_extracted (#90/#104): tracks whether face extraction fully completed
# for a photo. Upgrade path: photos that already have face rows were extracted
# by a pre-flag version, so backfill them to 1 — otherwise every existing photo
# would be re-extracted, destroying named face assignments. Photos with zero
# faces stay 0 (cheap re-check). The backfill is a one-shot followup: it must
# NOT re-run on later connections, because after a crash a partially-extracted
# photo legitimately has face rows while its flag is 0.
PHOTOS_MIGRATIONS: list[tuple[str, str | None]] = [
    (
        "ALTER TABLE photos ADD COLUMN faces_extracted INTEGER NOT NULL DEFAULT 0",
        "UPDATE photos SET faces_extracted = 1 "
        "WHERE EXISTS (SELECT 1 FROM faces WHERE photo_id = photos.id)",
    ),
    # missing (#105): set when a scan of a reachable root no longer finds the
    # file on disk; cleared automatically if it reappears at the same path.
    ("ALTER TABLE photos ADD COLUMN missing INTEGER NOT NULL DEFAULT 0", None),
    # blur_score (#154): Laplacian-variance sharpness computed at scan time;
    # NULL = not yet scored (scored on the photo's next scan).
    ("ALTER TABLE photos ADD COLUMN blur_score REAL", None),
    # Duplicate detection (#155): size + perceptual hash captured at scan
    # time; content_hash (SHA-256) computed lazily only for same-size
    # candidates when the duplicates view is used.
    ("ALTER TABLE photos ADD COLUMN file_size INTEGER", None),
    ("ALTER TABLE photos ADD COLUMN phash INTEGER", None),
    ("ALTER TABLE photos ADD COLUMN content_hash TEXT", None),
    # Rotation suggestions (#160): EXIF orientation captured at scan time;
    # suggested_rotation (degrees CW) from the on-demand face probe;
    # rotation_checked marks photos the probe has already analyzed.
    ("ALTER TABLE photos ADD COLUMN exif_orientation INTEGER", None),
    ("ALTER TABLE photos ADD COLUMN suggested_rotation INTEGER", None),
    ("ALTER TABLE photos ADD COLUMN rotation_checked INTEGER NOT NULL DEFAULT 0", None),
    # rotation_dismissed (#195): a suggestion the user decided isn't needed.
    # Persistent and independent of the checkbox selection state — unlike
    # unchecking a card, dismissal survives reloads and future rescans.
    ("ALTER TABLE photos ADD COLUMN rotation_dismissed INTEGER NOT NULL DEFAULT 0", None),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_faces_photo     ON faces(photo_id)",
    "CREATE INDEX IF NOT EXISTS idx_faces_person    ON faces(person_id)",
    "CREATE INDEX IF NOT EXISTS idx_faces_status    ON faces(assign_status)",
    "CREATE INDEX IF NOT EXISTS idx_photos_path     ON photos(path)",
    "CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photos(taken_at)",
    "CREATE INDEX IF NOT EXISTS idx_photos_missing  ON photos(missing)",
    "CREATE INDEX IF NOT EXISTS idx_photos_phash    ON photos(phash)",
    "CREATE INDEX IF NOT EXISTS idx_photos_size     ON photos(file_size)",
    "CREATE INDEX IF NOT EXISTS idx_scan_roots_path ON scan_roots(path)",
]

ALL_TABLES = [PHOTOS, FACES, PEOPLE, CORRECTIONS, SCAN_STATE, SCAN_ROOTS]
ALL_MIGRATIONS: list[tuple[str, str | None]] = SCAN_ROOTS_MIGRATIONS + PHOTOS_MIGRATIONS
