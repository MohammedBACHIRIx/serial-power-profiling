"""SQLite time-series storage: schema, batched Writer, read-only Reader.

Concurrency model (one writer + many readers):
  - WAL journal mode so readers never block the single writer.
  - Exactly one writer process, enforced by an OS file lock (see WriterLock).
  - Readers open the DB read-only, one connection per thread, short
    autocommit SELECTs with a per-device high-water-mark cursor.

The schema is pairing-ready: device.role / device.pair_id let input->output
efficiency grouping be added later purely in query/UI code, with no migration.
"""

import os
import sqlite3
import sys
import time

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS device (
    id         INTEGER PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    role       TEXT NOT NULL DEFAULT 'standalone',
    pair_id    INTEGER REFERENCES device(id),
    com_hint   TEXT,
    hwid       TEXT,
    created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session (
    id         INTEGER PRIMARY KEY,
    started_ts REAL NOT NULL,
    ended_ts   REAL,
    note       TEXT
);
CREATE TABLE IF NOT EXISTS sample (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES device(id),
    session_id INTEGER REFERENCES session(id),
    ts         REAL NOT NULL,
    power_w    REAL,
    voltage_v  REAL,
    current_a  REAL,
    pf         REAL,
    var_var    REAL,
    energy_wh  REAL,
    v_range    TEXT,
    i_range    TEXT,
    flags      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sample_dev_ts ON sample(device_id, ts);
CREATE TABLE IF NOT EXISTS device_health (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES device(id),
    ts         REAL NOT NULL,
    state      TEXT NOT NULL,
    detail     TEXT,
    com_port   TEXT
);
CREATE TABLE IF NOT EXISTS alert (
    id           INTEGER PRIMARY KEY,
    device_id    INTEGER NOT NULL REFERENCES device(id),
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL,
    value        REAL,
    threshold    REAL,
    message      TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS command (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES device(id),
    command    TEXT NOT NULL,
    created_ts REAL NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    done_ts    REAL
);
CREATE INDEX IF NOT EXISTS ix_command_pending ON command(device_id, status);
"""


class StoragePathError(Exception):
    """Raised when the chosen DB path is unsafe for a WAL database."""


def validate_db_path(path):
    """Reject paths where WAL is known to corrupt (network / cloud-synced).

    Returns the absolute path on success; raises StoragePathError otherwise.
    """
    abspath = os.path.abspath(path)
    low = abspath.lower().replace("\\", "/")
    if abspath.startswith("\\\\"):
        raise StoragePathError("DB path is a UNC/network share; WAL requires local disk.")
    for marker in ("/onedrive", "/dropbox", "/google drive", "/googledrive"):
        if marker in low:
            raise StoragePathError(
                "DB path appears to be inside a cloud-synced folder (%s); "
                "WAL databases corrupt there. Use a local path such as "
                "%%LOCALAPPDATA%%\\powerprofiler." % marker.strip("/")
            )
    return abspath


def default_db_path():
    """A safe default DB location under %LOCALAPPDATA% (or ~/.local on POSIX)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "powerprofiler", "powerprofiler.db")


def _connect(path, read_only=False):
    if read_only:
        uri = "file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/")
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.execute("PRAGMA query_only=ON")
    else:
        # check_same_thread=False: the Writer is handed from the thread that
        # constructs it to the single db-writer thread. We serialize access
        # ourselves (never two threads at once), so this is safe.
        conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path):
    """Create the schema (idempotent) and stamp the schema version.

    Must be called once by the writer before any reader connects.
    """
    abspath = validate_db_path(path)
    os.makedirs(os.path.dirname(abspath), exist_ok=True)
    conn = _connect(abspath, read_only=False)
    try:
        conn.executescript(_SCHEMA)
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        if ver == 0:
            conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
        conn.commit()
    finally:
        conn.close()
    return abspath


# --- Single-writer OS lock ------------------------------------------------
class WriterLock:
    """Exclusive, OS-level lock guaranteeing at most one logger writes the DB.

    Prevents the classic two-writer "database is locked"/corruption failure.
    Uses msvcrt on Windows and fcntl on POSIX. The lock file sits next to the
    DB and is held for the lifetime of the logger process.
    """

    def __init__(self, db_path):
        self.lock_path = os.path.abspath(db_path) + ".lock"
        self._fh = None

    def acquire(self):
        # The lock is opened before the Writer creates the DB, so on a fresh
        # install the parent directory may not exist yet. Create it first.
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        self._fh = open(self.lock_path, "a+")
        try:
            self._fh.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            raise RuntimeError(
                "Another logger already owns %s. Only one logger may write the DB."
                % self.lock_path
            )
        try:
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.write("%d\n" % os.getpid())
            self._fh.flush()
        except OSError:
            pass
        return self

    def release(self):
        if self._fh is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


# Columns written for each sample, in order.
_SAMPLE_COLS = (
    "device_id", "session_id", "ts", "power_w", "voltage_v", "current_a",
    "pf", "var_var", "energy_wh", "v_range", "i_range", "flags",
)


class Writer:
    """The single writer. Batches sample inserts and commits periodically.

    Intended to be driven from one dedicated thread so that disk writes never
    block device reader threads. Call enqueue()/record_* from that thread, and
    flush() on a timer (every `batch_ms`).
    """

    def __init__(self, db_path, batch_ms=250):
        self.db_path = init_db(db_path)
        self.batch_ms = batch_ms
        self._conn = _connect(self.db_path, read_only=False)
        self._pending = []
        self.session_id = None

    # -- device registry ---------------------------------------------------
    def get_or_create_device(self, name, role="standalone", com_hint=None, hwid=None):
        row = self._conn.execute(
            "SELECT id FROM device WHERE name=?", (name,)
        ).fetchone()
        if row:
            if com_hint is not None or hwid is not None:
                self._conn.execute(
                    "UPDATE device SET com_hint=COALESCE(?, com_hint), "
                    "hwid=COALESCE(?, hwid) WHERE id=?",
                    (com_hint, hwid, row["id"]),
                )
                self._conn.commit()
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO device(name, role, com_hint, hwid, created_ts) "
            "VALUES(?,?,?,?,?)",
            (name, role, com_hint, hwid, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    def start_session(self, note=None):
        cur = self._conn.execute(
            "INSERT INTO session(started_ts, note) VALUES(?,?)",
            (time.time(), note),
        )
        self._conn.commit()
        self.session_id = cur.lastrowid
        return self.session_id

    def end_session(self):
        if self.session_id is not None:
            self._conn.execute(
                "UPDATE session SET ended_ts=? WHERE id=?",
                (time.time(), self.session_id),
            )
            self._conn.commit()

    # -- sample batching ---------------------------------------------------
    def enqueue(self, device_id, ts, power_w, voltage_v, current_a, pf,
                var_var, energy_wh, v_range, i_range, flags):
        self._pending.append((
            device_id, self.session_id, ts, power_w, voltage_v, current_a,
            pf, var_var, energy_wh, v_range, i_range, flags,
        ))

    def flush(self):
        if not self._pending:
            return 0
        n = len(self._pending)
        placeholders = ",".join("?" * len(_SAMPLE_COLS))
        self._conn.executemany(
            "INSERT INTO sample(%s) VALUES(%s)" % (",".join(_SAMPLE_COLS), placeholders),
            self._pending,
        )
        self._conn.commit()
        self._pending.clear()
        return n

    # -- health / alerts ---------------------------------------------------
    def record_health(self, device_id, state, detail=None, com_port=None):
        self._conn.execute(
            "INSERT INTO device_health(device_id, ts, state, detail, com_port) "
            "VALUES(?,?,?,?,?)",
            (device_id, time.time(), state, detail, com_port),
        )
        self._conn.commit()

    def record_alert(self, device_id, kind, value, threshold, message):
        self._conn.execute(
            "INSERT INTO alert(device_id, ts, kind, value, threshold, message) "
            "VALUES(?,?,?,?,?,?)",
            (device_id, time.time(), kind, value, threshold, message),
        )
        self._conn.commit()

    # -- command queue (GUI -> workers) ------------------------------------
    def claim_pending_commands(self, device_id):
        """Return and mark 'sent' all pending commands for a device."""
        rows = self._conn.execute(
            "SELECT id, command FROM command "
            "WHERE device_id=? AND status='pending' ORDER BY id",
            (device_id,),
        ).fetchall()
        for r in rows:
            self._conn.execute(
                "UPDATE command SET status='sent', done_ts=? WHERE id=?",
                (time.time(), r["id"]),
            )
        if rows:
            self._conn.commit()
        return [(r["id"], r["command"]) for r in rows]

    def checkpoint(self):
        """Truncate the WAL file so it does not grow without bound."""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass

    def close(self):
        try:
            self.flush()
        finally:
            self._conn.close()


class Reader:
    """Read-only accessor for the GUI. One instance (and connection) per thread."""

    def __init__(self, db_path):
        self.db_path = os.path.abspath(db_path)
        self._conn = _connect(self.db_path, read_only=True)

    def devices(self):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM device ORDER BY id").fetchall()]

    def samples_after(self, device_id, after_id=0, limit=5000):
        """Incremental fetch by row id (the high-water-mark cursor)."""
        rows = self._conn.execute(
            "SELECT * FROM sample WHERE device_id=? AND id>? ORDER BY id LIMIT ?",
            (device_id, after_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def samples_in_range(self, device_id, start_ts, end_ts):
        rows = self._conn.execute(
            "SELECT * FROM sample WHERE device_id=? AND ts>=? AND ts<=? ORDER BY ts",
            (device_id, start_ts, end_ts),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_health(self, device_id):
        row = self._conn.execute(
            "SELECT * FROM device_health WHERE device_id=? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
        return dict(row) if row else None

    def unacked_alerts(self):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM alert WHERE acknowledged=0 ORDER BY id DESC").fetchall()]

    def close(self):
        self._conn.close()


# --- GUI control writes ---------------------------------------------------
# The GUI is not the sample writer, but it performs tiny, infrequent writes:
# queuing a device command and acknowledging alerts. These use a short-lived
# read-write connection (open -> write -> commit -> close) so lock contention
# with the logger's writer is negligible under WAL + busy_timeout.
def send_command(db_path, device_id, command):
    conn = _connect(db_path, read_only=False)
    try:
        conn.execute(
            "INSERT INTO command(device_id, command, created_ts, status) "
            "VALUES(?,?,?, 'pending')",
            (device_id, command, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def ack_alert(db_path, alert_id):
    conn = _connect(db_path, read_only=False)
    try:
        conn.execute("UPDATE alert SET acknowledged=1 WHERE id=?", (alert_id,))
        conn.commit()
    finally:
        conn.close()



