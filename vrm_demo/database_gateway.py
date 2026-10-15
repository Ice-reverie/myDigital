"""Database access for fictional health-service demo data.

The checked-in SQLite database is a seed. Runtime writes go to an ignored copy.
MySQL uses the same repository contract but is never initialized automatically.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import uuid


ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "digitalhelper_demo.sqlite3"
DEFAULT_RUNTIME_PATH = ROOT / "output" / "digitalhelper_demo.sqlite3"
DEMO_USER_ID = "demo-001"
CHINA_TIME = timezone(timedelta(hours=8))
_COPY_LOCK = threading.Lock()


class DatabaseUnavailable(Exception):
    pass


class SlotUnavailable(Exception):
    pass


def now():
    return datetime.now(CHINA_TIME)


def enabled():
    return os.getenv("DIGITALHELPER_DB_ENABLED", "false").strip().lower() in {"true", "1", "yes", "on"}


def backend():
    return os.getenv("DIGITALHELPER_DB_BACKEND", "sqlite").strip().lower() or "sqlite"


def runtime_path():
    value = os.getenv("DIGITALHELPER_SQLITE_PATH", "").strip()
    if not value:
        return DEFAULT_RUNTIME_PATH
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def _copy_seed():
    target = runtime_path()
    if target == SEED_PATH:
        raise DatabaseUnavailable("Runtime database cannot be the checked-in seed")
    with _COPY_LOCK:
        if target.exists():
            return target
        if not SEED_PATH.is_file():
            raise DatabaseUnavailable("SQLite demo seed is missing")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix="db-copy-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                with SEED_PATH.open("rb") as source:
                    shutil.copyfileobj(source, stream)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return target


def fill_future_slots(connection, today=None):
    """Materialize the next 14 China-local dates from fictional weekly patterns."""
    today = today or now().date()
    patterns = connection.execute(
        "SELECT dept_id, weekday, slot_id, capacity, base_booked, status FROM schedule_pattern"
    ).fetchall()
    if not patterns:
        return
    by_day = {}
    for row in patterns:
        by_day.setdefault(row[1], []).append(row)
    rows = []
    for offset in range(14):
        day = today + timedelta(days=offset)
        for pattern in by_day.get(day.weekday(), []):
            dept_id, _, slot_id, capacity, base_booked, status = pattern
            rows.append((f"{dept_id}:{day.isoformat()}:{slot_id}", dept_id,
                         day.isoformat(), slot_id, capacity, base_booked, status))
    connection.executemany(
        "INSERT OR IGNORE INTO schedule "
        "(schedule_id, dept_id, service_date, slot_id, capacity, base_booked, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", rows,
    )
    connection.commit()


@contextmanager
def repository():
    if not enabled():
        raise DatabaseUnavailable("Database feature is disabled")
    selected = backend()
    connection = None
    try:
        if selected == "sqlite":
            connection = sqlite3.connect(_copy_seed(), timeout=3)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            fill_future_slots(connection)
        elif selected == "mysql":
            try:
                import mysql.connector
            except ImportError as exc:
                raise DatabaseUnavailable("Install requirements-mysql.txt to use MySQL") from exc
            database = os.getenv("DIGITALHELPER_MYSQL_DATABASE", "").strip()
            user = os.getenv("DIGITALHELPER_MYSQL_USER", "").strip()
            if not database or not user:
                raise DatabaseUnavailable("MySQL database and user are required")
            connection = mysql.connector.connect(
                host=os.getenv("DIGITALHELPER_MYSQL_HOST", "127.0.0.1").strip(),
                port=int(os.getenv("DIGITALHELPER_MYSQL_PORT", "3306")),
                database=database,
                user=user,
                password=os.getenv("DIGITALHELPER_MYSQL_PASSWORD", ""),
                connection_timeout=2,
                autocommit=True,
                charset="utf8mb4",
            )
        else:
            raise DatabaseUnavailable("Unsupported database backend")
        yield Repository(connection, selected)
    finally:
        if connection is not None:
            connection.close()


def status():
    result = {"db_enabled": enabled(), "db_backend": backend(), "db_available": False}
    if not result["db_enabled"]:
        return result
    try:
        with repository() as store:
            store.one("SELECT dept_id FROM department LIMIT 1")
        result["db_available"] = True
    except Exception:
        pass
    return result


class Repository:
    def __init__(self, connection, dialect):
        self.connection = connection
        self.dialect = dialect

    def _sql(self, statement):
        return statement if self.dialect == "sqlite" else statement.replace("?", "%s")

    def _cursor(self, statement, parameters=()):
        if self.dialect == "sqlite":
            return self.connection.execute(statement, parameters)
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(self._sql(statement), parameters)
        return cursor

    def one(self, statement, parameters=()):
        cursor = self._cursor(statement, parameters)
        try:
            row = cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            cursor.close()

    def all(self, statement, parameters=()):
        cursor = self._cursor(statement, parameters)
        try:
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def execute(self, statement, parameters=()):
        cursor = self._cursor(statement, parameters)
        try:
            return cursor.rowcount
        finally:
            cursor.close()

    @contextmanager
    def transaction(self):
        if self.dialect == "sqlite":
            self.connection.execute("BEGIN IMMEDIATE")
        else:
            self.connection.start_transaction()
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def departments(self):
        return self.all("SELECT dept_id, dept_name, location, services, opening_hours "
                        "FROM department WHERE status = 1 ORDER BY sort_no, dept_name")

    def service_info(self):
        return self.all("SELECT info_key, title, content FROM service_info ORDER BY info_key")

    def slots(self, dept_id, today=None):
        today = today or now().date()
        until = today + timedelta(days=14)
        return self.all(
            "SELECT s.schedule_id, s.dept_id, s.service_date, s.capacity, s.base_booked, "
            "s.status, t.slot_name, t.start_time, t.end_time, t.slot_order, "
            "(SELECT COUNT(*) FROM appointment a WHERE a.schedule_id = s.schedule_id "
            "AND a.status = 'confirmed') AS new_booked "
            "FROM schedule s JOIN time_slot t ON t.slot_id = s.slot_id "
            "WHERE s.dept_id = ? AND s.service_date >= ? AND s.service_date < ? "
            "ORDER BY s.service_date, t.slot_order",
            (dept_id, today.isoformat(), until.isoformat()),
        )

    def slot(self, schedule_id, lock=False):
        statement = (
            "SELECT s.schedule_id, s.dept_id, s.service_date, s.capacity, s.base_booked, "
            "s.status, t.slot_name, t.start_time, d.dept_name "
            "FROM schedule s JOIN time_slot t ON t.slot_id = s.slot_id "
            "JOIN department d ON d.dept_id = s.dept_id WHERE s.schedule_id = ?"
        )
        if lock and self.dialect == "mysql":
            statement += " FOR UPDATE"
        return self.one(statement, (schedule_id,))

    def book(self, schedule_id, booking_token, today=None):
        today = today or now().date()
        with self.transaction():
            # MySQL locks the dated slot before the idempotency lookup, so a
            # concurrent retry observes the first request after it commits.
            slot = self.slot(schedule_id, lock=True)
            existing = self.one(
                "SELECT appointment_id, schedule_id, queue_no FROM appointment "
                "WHERE booking_token = ? AND user_id = ? AND status = 'confirmed'",
                (booking_token, DEMO_USER_ID),
            )
            if existing:
                return {**existing, "repeated": True}
            service_date = slot["service_date"] if slot else None
            if hasattr(service_date, "isoformat"):
                service_date = service_date.isoformat()
            if (not slot or slot["status"] != "open" or
                    not today.isoformat() <= service_date < (today + timedelta(days=14)).isoformat()):
                raise SlotUnavailable("This slot is no longer available")
            count = self.one(
                "SELECT COUNT(*) AS total FROM appointment WHERE schedule_id = ? "
                "AND status = 'confirmed'", (schedule_id,),
            )["total"]
            ahead = slot["base_booked"] + count
            if ahead >= slot["capacity"]:
                raise SlotUnavailable("This slot is full")
            appointment_id = uuid.uuid4().hex
            self.execute(
                "INSERT INTO appointment "
                "(appointment_id, booking_token, user_id, schedule_id, queue_no, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'confirmed', ?)",
                (appointment_id, booking_token, DEMO_USER_ID, schedule_id,
                 ahead + 1, now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            return {"appointment_id": appointment_id, "schedule_id": schedule_id,
                    "queue_no": ahead + 1, "repeated": False}

    def appointments(self):
        return self.all(
            "SELECT a.appointment_id, a.queue_no, s.service_date, t.slot_name, d.dept_name "
            "FROM appointment a JOIN schedule s ON s.schedule_id = a.schedule_id "
            "JOIN time_slot t ON t.slot_id = s.slot_id "
            "JOIN department d ON d.dept_id = s.dept_id "
            "WHERE a.user_id = ? AND a.status = 'confirmed' "
            "ORDER BY s.service_date DESC, t.slot_order DESC LIMIT 5", (DEMO_USER_ID,),
        )

    def records(self, keyword=None):
        statement = ("SELECT record_type, content, recorded_at FROM health_record "
                     "WHERE user_id = ?")
        parameters = [DEMO_USER_ID]
        if keyword:
            statement += " AND content LIKE ?"
            parameters.append(f"%{keyword}%")
        statement += " ORDER BY recorded_at DESC LIMIT 3"
        return self.all(statement, tuple(parameters))

    def alerts(self):
        return self.all(
            "SELECT alert_id, alert_content, status, alert_time FROM alert "
            "WHERE user_id = ? ORDER BY alert_time DESC LIMIT 5", (DEMO_USER_ID,),
        )

    def handle_alert(self, alert_id, new_status):
        if new_status not in {"confirmed", "family_requested", "later"}:
            raise ValueError("Invalid alert status")
        with self.transaction():
            statement = "SELECT alert_id, status FROM alert WHERE alert_id = ? AND user_id = ?"
            if self.dialect == "mysql":
                statement += " FOR UPDATE"
            alert = self.one(statement, (alert_id, DEMO_USER_ID))
            if alert is None:
                return None
            if alert["status"] == "pending":
                self.execute(
                    "UPDATE alert SET status = ?, handled_at = ? "
                    "WHERE alert_id = ? AND user_id = ?",
                    (new_status, now().strftime("%Y-%m-%d %H:%M:%S"),
                     alert_id, DEMO_USER_ID),
                )
                return new_status
            return alert["status"]
