PRAGMA foreign_keys = ON;

CREATE TABLE department (
    dept_id TEXT PRIMARY KEY,
    dept_name TEXT NOT NULL UNIQUE,
    location TEXT NOT NULL,
    services TEXT NOT NULL,
    opening_hours TEXT NOT NULL,
    sort_no INTEGER NOT NULL,
    status INTEGER NOT NULL CHECK (status IN (0, 1))
);

CREATE TABLE time_slot (
    slot_id TEXT PRIMARY KEY,
    slot_name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    slot_order INTEGER NOT NULL
);

CREATE TABLE schedule_pattern (
    dept_id TEXT NOT NULL REFERENCES department(dept_id),
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    slot_id TEXT NOT NULL REFERENCES time_slot(slot_id),
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    base_booked INTEGER NOT NULL CHECK (base_booked BETWEEN 0 AND capacity),
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    PRIMARY KEY (dept_id, weekday, slot_id)
);

CREATE TABLE schedule (
    schedule_id TEXT PRIMARY KEY,
    dept_id TEXT NOT NULL REFERENCES department(dept_id),
    service_date TEXT NOT NULL,
    slot_id TEXT NOT NULL REFERENCES time_slot(slot_id),
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    base_booked INTEGER NOT NULL CHECK (base_booked BETWEEN 0 AND capacity),
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    UNIQUE (dept_id, service_date, slot_id)
);
CREATE INDEX idx_schedule_date ON schedule(service_date, dept_id);

CREATE TABLE user_base (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    is_demo INTEGER NOT NULL CHECK (is_demo = 1)
);

CREATE TABLE appointment (
    appointment_id TEXT PRIMARY KEY,
    booking_token TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES user_base(user_id),
    schedule_id TEXT NOT NULL REFERENCES schedule(schedule_id),
    queue_no INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled')),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_appointment_schedule ON appointment(schedule_id, status);
CREATE INDEX idx_appointment_user ON appointment(user_id, created_at);

CREATE TABLE health_record (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES user_base(user_id),
    record_type TEXT NOT NULL,
    content TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX idx_health_user_date ON health_record(user_id, recorded_at);

CREATE TABLE alert (
    alert_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES user_base(user_id),
    alert_content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'family_requested', 'later')),
    alert_time TEXT NOT NULL,
    handled_at TEXT
);
CREATE INDEX idx_alert_user_status ON alert(user_id, status, alert_time);

CREATE TABLE service_info (
    info_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL
);
