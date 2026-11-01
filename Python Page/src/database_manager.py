"""Local SQLite storage. No remote connection or credentials are used."""
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ANALYTICS_DB, BASE_DIR

LOCAL_TIMEZONE = timezone(timedelta(hours=8))

def get_local_datetime():
    return datetime.now(LOCAL_TIMEZONE)

class DatabaseManager:
    def __init__(self, db_path=None, import_archives=True):
        self.path = Path(db_path or ANALYTICS_DB).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.record_interval = 180
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS recognition_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL, time TEXT NOT NULL, name TEXT NOT NULL,
                    emotion TEXT, confidence REAL, recorded_at REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS recognition_name_time
                    ON recognition_records(name, recorded_at);
                CREATE TABLE IF NOT EXISTS flow_records (
                    date TEXT PRIMARY KEY, left_to_right INTEGER NOT NULL DEFAULT 0,
                    right_to_left INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS flow_events (
                    event_id TEXT PRIMARY KEY, date TEXT NOT NULL,
                    time TEXT NOT NULL, direction TEXT NOT NULL,
                    track_id INTEGER NOT NULL, axis TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            """)
        if import_archives:
            self._import_archives()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _import_archives(self):
        """Copy the supplied archive once; never modify the original files."""
        with self.connection() as dest:
            if dest.execute("SELECT 1 FROM metadata WHERE key='archive_import_v1'").fetchone():
                return
            archive_dir = BASE_DIR / "data" / "achieve"
            for name in ("recognition_records.db", "flow_records.db"):
                path = archive_dir / name
                if not path.is_file():
                    continue
                source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                try:
                    if name.startswith("recognition"):
                        rows = source.execute("SELECT date,time,name,emotion,confidence FROM recognition_records").fetchall()
                        dest.executemany("INSERT INTO recognition_records(date,time,name,emotion,confidence) VALUES(?,?,?,?,?)", rows)
                    else:
                        for date, forward, backward in source.execute("SELECT date,left_to_right,right_to_left FROM flow_records"):
                            dest.execute("""
                                INSERT INTO flow_records VALUES(?,?,?)
                                ON CONFLICT(date) DO UPDATE SET
                                left_to_right=MAX(left_to_right,excluded.left_to_right),
                                right_to_left=MAX(right_to_left,excluded.right_to_left)
                            """, (date, forward or 0, backward or 0))
                finally:
                    source.close()
            dest.execute("INSERT INTO metadata VALUES('archive_import_v1','done')")

    def add_record(self, name, emotion, confidence):
        now = time.time()
        stamp = get_local_datetime()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            last = conn.execute("SELECT MAX(recorded_at) FROM recognition_records WHERE name=?", (name,)).fetchone()[0]
            if last and now - last < self.record_interval:
                return False
            conn.execute(
                "INSERT INTO recognition_records(date,time,name,emotion,confidence,recorded_at) VALUES(?,?,?,?,?,?)",
                (stamp.date().isoformat(), stamp.strftime("%H:%M:%S"), name, emotion, float(confidence), now),
            )
        return True

    def get_records(self, limit=100):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT date,time,name,emotion,confidence FROM recognition_records ORDER BY id DESC LIMIT ?",
                (min(max(int(limit), 1), 1000),),
            )]

    def get_counts(self, date=None):
        date = date or get_local_datetime().date().isoformat()
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM flow_records WHERE date=?", (date,)).fetchone()
        return dict(row) if row else {"date": date, "left_to_right": 0, "right_to_left": 0}

    def record_crossings(self, events, axis="x"):
        stamp = get_local_datetime()
        date = stamp.date().isoformat()
        with self.connection() as conn:
            for event in events:
                direction = event["direction"]
                if direction not in ("left_to_right", "right_to_left"):
                    raise ValueError("Invalid crossing direction")
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO flow_events VALUES(?,?,?,?,?,?)",
                    (event["event_id"], date, stamp.strftime("%H:%M:%S"), direction, int(event["track_id"]), axis),
                )
                if cursor.rowcount:
                    conn.execute("""
                        INSERT INTO flow_records VALUES(?,?,?)
                        ON CONFLICT(date) DO UPDATE SET
                        left_to_right=left_to_right+excluded.left_to_right,
                        right_to_left=right_to_left+excluded.right_to_left
                    """, (date, int(direction == "left_to_right"), int(direction == "right_to_left")))
        return self.get_counts(date)

    def reset_counts(self):
        date = get_local_datetime().date().isoformat()
        with self.connection() as conn:
            conn.execute("DELETE FROM flow_events WHERE date=?", (date,))
            conn.execute("INSERT INTO flow_records VALUES(?,0,0) ON CONFLICT(date) DO UPDATE SET left_to_right=0,right_to_left=0", (date,))
        return self.get_counts(date)

    def get_flow_records(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM flow_records ORDER BY date DESC LIMIT 365")]
