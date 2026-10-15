-- Apply manually to an empty MySQL database. All rows used by the demo must be fictional.
CREATE TABLE department (
    dept_id VARCHAR(32) PRIMARY KEY,
    dept_name VARCHAR(64) NOT NULL UNIQUE,
    location VARCHAR(120) NOT NULL,
    services VARCHAR(500) NOT NULL,
    opening_hours VARCHAR(120) NOT NULL,
    sort_no INT NOT NULL,
    status TINYINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE time_slot (
    slot_id VARCHAR(32) PRIMARY KEY,
    slot_name VARCHAR(64) NOT NULL,
    start_time CHAR(5) NOT NULL,
    end_time CHAR(5) NOT NULL,
    slot_order INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE schedule_pattern (
    dept_id VARCHAR(32) NOT NULL,
    weekday TINYINT NOT NULL,
    slot_id VARCHAR(32) NOT NULL,
    capacity INT NOT NULL,
    base_booked INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    PRIMARY KEY (dept_id, weekday, slot_id),
    FOREIGN KEY (dept_id) REFERENCES department(dept_id),
    FOREIGN KEY (slot_id) REFERENCES time_slot(slot_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE schedule (
    schedule_id VARCHAR(80) PRIMARY KEY,
    dept_id VARCHAR(32) NOT NULL,
    service_date DATE NOT NULL,
    slot_id VARCHAR(32) NOT NULL,
    capacity INT NOT NULL,
    base_booked INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    UNIQUE KEY uq_schedule (dept_id, service_date, slot_id),
    INDEX idx_schedule_date (service_date, dept_id),
    FOREIGN KEY (dept_id) REFERENCES department(dept_id),
    FOREIGN KEY (slot_id) REFERENCES time_slot(slot_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user_base (
    user_id VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(64) NOT NULL,
    is_demo TINYINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE appointment (
    appointment_id VARCHAR(64) PRIMARY KEY,
    booking_token VARCHAR(64) NOT NULL UNIQUE,
    user_id VARCHAR(32) NOT NULL,
    schedule_id VARCHAR(80) NOT NULL,
    queue_no INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at DATETIME NOT NULL,
    INDEX idx_appointment_schedule (schedule_id, status),
    INDEX idx_appointment_user (user_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user_base(user_id),
    FOREIGN KEY (schedule_id) REFERENCES schedule(schedule_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE health_record (
    record_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(32) NOT NULL,
    record_type VARCHAR(32) NOT NULL,
    content VARCHAR(500) NOT NULL,
    recorded_at DATETIME NOT NULL,
    INDEX idx_health_user_date (user_id, recorded_at),
    FOREIGN KEY (user_id) REFERENCES user_base(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE alert (
    alert_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(32) NOT NULL,
    alert_content VARCHAR(500) NOT NULL,
    status VARCHAR(24) NOT NULL,
    alert_time DATETIME NOT NULL,
    handled_at DATETIME NULL,
    INDEX idx_alert_user_status (user_id, status, alert_time),
    FOREIGN KEY (user_id) REFERENCES user_base(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE service_info (
    info_key VARCHAR(64) PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    content VARCHAR(500) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
