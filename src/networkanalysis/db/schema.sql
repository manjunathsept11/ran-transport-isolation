-- RAN & Transport Isolation - SQLite warehouse schema (system of record).
-- Bulky raw feeds also live as day-partitioned parquet under data/raw/; this DB holds
-- dimensions, ground truth, aggregated facts, and all serving/analytics tables.

PRAGMA foreign_keys = ON;

-- ======================= dimensions =======================
CREATE TABLE IF NOT EXISTS dim_site (
    site_id              TEXT PRIMARY KEY,
    region               TEXT NOT NULL,
    morphology           TEXT NOT NULL,
    lat                  REAL, lon REAL,
    backhaul_type        TEXT,
    n_sectors            INTEGER,
    design_capacity_mbps REAL
);

CREATE TABLE IF NOT EXISTS dim_cell (
    cell_id        TEXT PRIMARY KEY,
    site_id        TEXT NOT NULL REFERENCES dim_site(site_id),
    sector         INTEGER, azimuth_deg INTEGER,
    band           TEXT, carrier_ghz REAL,
    cell_radius_km REAL, capacity_mbps REAL
);
CREATE INDEX IF NOT EXISTS ix_cell_site ON dim_cell(site_id);

CREATE TABLE IF NOT EXISTS dim_router (
    router_id   TEXT PRIMARY KEY,
    role        TEXT NOT NULL,
    region      TEXT,
    site_count  INTEGER
);

CREATE TABLE IF NOT EXISTS dim_link (
    link_id       TEXT PRIMARY KEY,
    endpoint_a    TEXT NOT NULL,
    endpoint_b    TEXT NOT NULL,
    media         TEXT,
    kind          TEXT,          -- access | preagg_uplink | agg_uplink
    capacity_mbps REAL
);
CREATE INDEX IF NOT EXISTS ix_link_kind ON dim_link(kind);

CREATE TABLE IF NOT EXISTS dim_path_link (
    site_id    TEXT NOT NULL REFERENCES dim_site(site_id),
    hop_index  INTEGER NOT NULL,
    link_id    TEXT NOT NULL REFERENCES dim_link(link_id),
    PRIMARY KEY (site_id, hop_index)
);
CREATE INDEX IF NOT EXISTS ix_path_link ON dim_path_link(link_id);

CREATE TABLE IF NOT EXISTS dim_twamp_session (
    twamp_session_id TEXT PRIMARY KEY,
    link_id          TEXT NOT NULL REFERENCES dim_link(link_id),
    endpoint_a       TEXT, endpoint_b TEXT
);

CREATE TABLE IF NOT EXISTS dim_sevone_interface (
    sevone_if_id  TEXT PRIMARY KEY,
    link_id       TEXT NOT NULL REFERENCES dim_link(link_id),
    router_id     TEXT,
    if_speed_mbps REAL
);

-- Ground truth: every injected fault.
CREATE TABLE IF NOT EXISTS dim_incident (
    incident_id       TEXT PRIMARY KEY,
    incident_class    TEXT NOT NULL,      -- transport | ran | shared
    kind              TEXT NOT NULL,
    start_ts          TEXT NOT NULL,
    end_ts            TEXT NOT NULL,
    magnitude         REAL,
    root_entity       TEXT,
    root_entity_type  TEXT,               -- link | sector | site | router
    n_affected_sites  INTEGER,
    affected_site_ids TEXT,               -- JSON array
    affected_link_ids TEXT,               -- JSON array
    affected_sectors  TEXT,               -- JSON array
    auto_generated    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_incident_time ON dim_incident(start_ts, end_ts);

-- ======================= facts (5-min) =======================
CREATE TABLE IF NOT EXISTS fact_site_bin (
    ts TEXT NOT NULL, site_id TEXT NOT NULL,
    offered_mbps REAL, prb_util_pct REAL, rsrp_dbm REAL, rsrq_db REAL,
    sched_delay_ms REAL, path_delay_ms REAL, path_jitter_ms REAL, path_loss_pct REAL,
    path_capacity_mbps REAL, radio_capacity_mbps REAL,
    tcp_client_rtt_ms REAL, tcp_server_rtt_ms REAL, tcp_fail_pct REAL, retrans_pct REAL,
    vonr_mos REAL, dl_throughput_mbps REAL, ul_throughput_mbps REAL, loaded_latency_ms REAL,
    youtube_qoe_mos REAL, rebuffer_ratio REAL, sessions REAL, users REAL, availability REAL
);
CREATE INDEX IF NOT EXISTS ix_site_bin ON fact_site_bin(site_id, ts);

CREATE TABLE IF NOT EXISTS fact_link_bin (
    ts TEXT NOT NULL, link_id TEXT NOT NULL,
    offered_mbps REAL, util_pct REAL, queue_occ REAL, delay_ms REAL, jitter_ms REAL,
    loss_pct REAL, discards_pps REAL, crc_rate REAL, availability REAL
);
CREATE INDEX IF NOT EXISTS ix_link_bin ON fact_link_bin(link_id, ts);

CREATE TABLE IF NOT EXISTS fact_twamp_5min (
    ts TEXT NOT NULL, link_id TEXT NOT NULL,
    rtt_ms REAL, owd_ms REAL, jitter_ms REAL, frame_loss_pct REAL
);
CREATE INDEX IF NOT EXISTS ix_twamp ON fact_twamp_5min(link_id, ts);

CREATE TABLE IF NOT EXISTS fact_sevone_5min (
    ts TEXT NOT NULL, link_id TEXT NOT NULL,
    in_util_pct REAL, out_util_pct REAL, queue_depth REAL, discards REAL,
    crc_errors REAL, if_errors REAL
);
CREATE INDEX IF NOT EXISTS ix_sevone ON fact_sevone_5min(link_id, ts);

CREATE TABLE IF NOT EXISTS fact_n3_5min (
    ts TEXT NOT NULL, site_id TEXT NOT NULL,
    tcp_client_rtt_ms REAL, tcp_server_rtt_ms REAL, tcp_fail_pct REAL, retrans_pct REAL,
    vonr_mos REAL, flow_count REAL, user_count REAL
);
CREATE INDEX IF NOT EXISTS ix_n3 ON fact_n3_5min(site_id, ts);

-- ======================= raw session records =======================
CREATE TABLE IF NOT EXISTS fact_ookla_test (
    test_id TEXT PRIMARY KEY, ts TEXT NOT NULL, site_id TEXT NOT NULL, cell_id TEXT,
    lat REAL, lon REAL, device_class TEXT,
    dl_mbps REAL, ul_mbps REAL, loaded_latency_ms REAL, rsrp_dbm REAL, rsrq_db REAL
);
CREATE INDEX IF NOT EXISTS ix_ookla_site ON fact_ookla_test(site_id, ts);

CREATE TABLE IF NOT EXISTS fact_qoe_session (
    session_id TEXT PRIMARY KEY, ts TEXT NOT NULL, site_id TEXT NOT NULL, cell_id TEXT,
    service TEXT, mos REAL, rebuffer_ratio REAL, startup_ms REAL, bitrate_kbps REAL
);
CREATE INDEX IF NOT EXISTS ix_qoe_site ON fact_qoe_session(site_id, ts);

-- ======================= rollups =======================
CREATE TABLE IF NOT EXISTS agg_site_hourly (
    ts_hour TEXT NOT NULL, site_id TEXT NOT NULL,
    rsrp_p50 REAL, rsrq_p50 REAL, prb_util_p95 REAL,
    tcp_client_rtt_ms REAL, tcp_server_rtt_ms REAL, tcp_fail_pct REAL, retrans_pct REAL,
    vonr_mos REAL, dl_throughput_mbps REAL, ul_throughput_mbps REAL, loaded_latency_ms REAL,
    youtube_qoe_mos REAL, rebuffer_ratio REAL,
    path_delay_ms REAL, path_jitter_ms REAL, path_loss_pct REAL,
    twamp_rtt_ms REAL, twamp_jitter_ms REAL, twamp_loss_pct REAL,
    sevone_util_pct REAL, sevone_queue_depth REAL, sevone_discards REAL, sevone_crc REAL,
    sessions REAL, users REAL, availability REAL,
    PRIMARY KEY (site_id, ts_hour)
);

CREATE TABLE IF NOT EXISTS agg_link_hourly (
    ts_hour TEXT NOT NULL, link_id TEXT NOT NULL,
    util_pct REAL, queue_occ REAL, delay_ms REAL, jitter_ms REAL, loss_pct REAL,
    discards_pps REAL, crc_rate REAL, availability REAL,
    PRIMARY KEY (link_id, ts_hour)
);

-- ======================= serving / analytics =======================
CREATE TABLE IF NOT EXISTS site_baseline (
    site_id TEXT NOT NULL, metric TEXT NOT NULL,
    own_median REAL, own_mad REAL, peer_median REAL, peer_mad REAL, direction INTEGER,
    PRIMARY KEY (site_id, metric)
);

CREATE TABLE IF NOT EXISTS site_scorecard (
    site_id TEXT PRIMARY KEY,
    region TEXT, morphology TEXT,
    rank INTEGER, impact_score REAL,
    severity_tcp_rtt REAL, severity_tcp_fail REAL, severity_throughput REAL,
    severity_vonr REAL, severity_youtube REAL,
    sessions_impacted REAL, users_impacted REAL,
    worst_window_start TEXT, worst_window_end TEXT,
    primary_attribution TEXT, attribution_confidence REAL,
    is_priority INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_scorecard_rank ON site_scorecard(rank);

CREATE TABLE IF NOT EXISTS impairment_attribution (
    site_id TEXT PRIMARY KEY,
    rule_class TEXT, rule_confidence REAL, rule_evidence TEXT,
    ml_class TEXT, ml_confidence REAL, ml_top_features TEXT,
    final_class TEXT, final_confidence REAL,
    matched_incident_id TEXT, matched_incident_class TEXT
);

CREATE TABLE IF NOT EXISTS anomaly_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT, entity_id TEXT, metric TEXT,
    start_ts TEXT, end_ts TEXT, peak_ts TEXT, severity REAL, method TEXT, direction INTEGER
);
CREATE INDEX IF NOT EXISTS ix_anom_entity ON anomaly_event(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS incident_detected (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts TEXT, end_ts TEXT, n_sites INTEGER, n_links INTEGER,
    site_ids TEXT, link_ids TEXT, severity REAL,
    predicted_class TEXT, confidence REAL,
    matched_incident_id TEXT, match_iou REAL
);

CREATE TABLE IF NOT EXISTS rca_finding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT, scope_id TEXT,
    candidate_cause TEXT, candidate_entity TEXT, cause_class TEXT,
    confidence REAL, evidence TEXT, recommended_action TEXT,
    detected_incident_id INTEGER, matched_incident_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_rca_scope ON rca_finding(scope, scope_id);

CREATE TABLE IF NOT EXISTS correlation_edge (
    scope TEXT, scope_id TEXT, metric_a TEXT, metric_b TEXT,
    spearman REAL, partial REAL, best_lag_min INTEGER, lag_corr REAL,
    PRIMARY KEY (scope, scope_id, metric_a, metric_b)
);

CREATE TABLE IF NOT EXISTS variability_site (
    site_id TEXT PRIMARY KEY,
    metric TEXT,
    cv REAL, iqr REAL, busy_offpeak_ratio REAL,
    within_day_var REAL, day_to_day_var REAL,
    stability_rank INTEGER, instability_flag INTEGER,
    wow_psi REAL, wow_shift INTEGER
);

-- ======================= operational metadata =======================
CREATE TABLE IF NOT EXISTS gen_run (
    run_id TEXT PRIMARY KEY,
    created_at TEXT, preset TEXT, seed INTEGER, topology_seed INTEGER,
    start_date TEXT, duration_days INTEGER, bin_seconds INTEGER,
    n_sites INTEGER, n_links INTEGER, n_incidents INTEGER,
    config_json TEXT, row_counts_json TEXT
);

CREATE TABLE IF NOT EXISTS job (
    job_id TEXT PRIMARY KEY,
    kind TEXT, status TEXT, progress REAL, message TEXT,
    created_at TEXT, updated_at TEXT, params_json TEXT, result_json TEXT
);

CREATE TABLE IF NOT EXISTS analytics_run (
    run_id TEXT PRIMARY KEY, created_at TEXT, gen_run_id TEXT,
    metrics_json TEXT
);

CREATE TABLE IF NOT EXISTS kv_meta (k TEXT PRIMARY KEY, v TEXT);
