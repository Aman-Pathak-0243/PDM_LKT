-- =============================================================================
-- Predictive Maintenance (PdM) — MySQL schema
--
-- STATUS: DESIGNED, NOT YET APPLIED. MySQL must not be used until the user grants
-- permission and shares the real database name. The active backend is CSV; this
-- file is the MySQL twin of core/storage/base.py (the runtime source of truth).
-- Apply idempotently (CREATE TABLE IF NOT EXISTS) once MySQL is enabled.
--
-- Conventions:
--   * Datetimes are stored as ISO-8601 strings (VARCHAR) for behavioural parity
--     with the CSV backend (lexicographic range filters + ordering).
--   * JSON columns hold flexible metadata (AI/ML, analytics, warehouse export).
--   * component_health is the longitudinal store; index (module, component_id, created_at).
-- =============================================================================

-- One row per PdM run (fetch -> features -> health -> persist).
CREATE TABLE IF NOT EXISTS pdm_run (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_uid           VARCHAR(64)  NOT NULL,
    module            VARCHAR(64)  NOT NULL,
    trigger_type      ENUM('manual','auto') NOT NULL,
    trigger_id        VARCHAR(64),
    data_window       VARCHAR(64),
    started_at        VARCHAR(32),
    finished_at       VARCHAR(32),
    status            VARCHAR(16),                 -- running|success|partial|failed
    rows_fetched      INT DEFAULT 0,
    components_scored INT DEFAULT 0,
    error             TEXT,
    created_at        VARCHAR(32)  NOT NULL,
    UNIQUE KEY uq_pdm_run_uid (run_uid),
    KEY ix_pdm_run_module_created (module, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- THE LONGITUDINAL STORE: one row per component per run.
CREATE TABLE IF NOT EXISTS component_health (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_uid             VARCHAR(64) NOT NULL,
    module              VARCHAR(64) NOT NULL,
    component_id        VARCHAR(128) NOT NULL,
    component_type      VARCHAR(64),
    health_score        DOUBLE,
    risk_tier           VARCHAR(16),               -- ok|watch|warn|critical
    predicted_ttm_hours DOUBLE,
    confidence          DOUBLE,
    prediction_regime   ENUM('coldstart','trend'),
    primary_cause       VARCHAR(255),
    rca_json            JSON,
    metrics_json        JSON,
    created_at          VARCHAR(32) NOT NULL,
    KEY ix_ch_module_component_created (module, component_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Machine-readable twin of Chapter 2 (the dashboards/panels catalog).
CREATE TABLE IF NOT EXISTS panel_catalog (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    module         VARCHAR(64) NOT NULL,
    dashboard_uid  VARCHAR(64) NOT NULL,
    dashboard_name VARCHAR(255),
    panel_id       INT NOT NULL,
    panel_title    VARCHAR(255),
    panel_type     VARCHAR(64),
    fields_json    JSON,
    sql_text       TEXT,
    is_signal      TINYINT(1) DEFAULT 0,
    role           VARCHAR(16),                    -- primary|secondary|none
    notes          TEXT,
    updated_at     VARCHAR(32) NOT NULL,
    UNIQUE KEY uq_panel (module, dashboard_uid, panel_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Automation schedule per scope ('global' or a module name).
CREATE TABLE IF NOT EXISTS automation_config (
    scope            VARCHAR(64) PRIMARY KEY,      -- 'global' or module name
    enabled          TINYINT(1) DEFAULT 0,
    interval_minutes INT DEFAULT 60,
    data_window      VARCHAR(64),
    updated_at       VARCHAR(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Optional operator acknowledgements (never drive detection).
CREATE TABLE IF NOT EXISTS maintenance_ack (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    module       VARCHAR(64) NOT NULL,
    component_id VARCHAR(128) NOT NULL,
    acked_by     VARCHAR(128),
    acked_at     VARCHAR(32) NOT NULL,
    note         TEXT,
    KEY ix_ack_module_component (module, component_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Traceable trigger executions (manual + automated).
CREATE TABLE IF NOT EXISTS trigger_log (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    trigger_id        VARCHAR(64) NOT NULL,
    trigger_type      ENUM('manual','auto'),
    module            VARCHAR(64),                 -- module name or 'all'
    status            VARCHAR(16),                 -- pending|running|success|partial|failed
    data_window       VARCHAR(64),
    started_at        VARCHAR(32),
    finished_at       VARCHAR(32),
    duration_ms       BIGINT,
    records_processed INT DEFAULT 0,
    success_count     INT DEFAULT 0,
    failure_count     INT DEFAULT 0,
    retry_count       INT DEFAULT 0,
    run_uids_json     JSON,
    message           TEXT,
    created_at        VARCHAR(32) NOT NULL,
    UNIQUE KEY uq_trigger (trigger_id),
    KEY ix_trigger_created (created_at),
    KEY ix_trigger_type_status (trigger_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Structured domain/audit events surfaced in the dashboard Logs page.
CREATE TABLE IF NOT EXISTS event_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts          VARCHAR(32) NOT NULL,
    level       VARCHAR(16),
    source      VARCHAR(128),
    event       VARCHAR(128) NOT NULL,
    module      VARCHAR(64),
    detail_json JSON,
    KEY ix_event_ts (ts),
    KEY ix_event_level (level),
    KEY ix_event_event (event)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
