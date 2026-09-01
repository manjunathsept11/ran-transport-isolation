---
name: network-analysis-context
description: >
  Context for the RAN & Transport Isolation warehouse (SQLite at data/warehouse.db):
  schema, KPI definitions, telecom terminology, and common query patterns. Use when
  writing SQL / analysis against this project's synthetic telecom data, interpreting the
  scorecard / attribution / anomaly tables, or answering questions about transport-vs-RAN
  isolation.
---

# RAN & Transport Isolation — data context

## Warehouse

SQLite, `data/warehouse.db` (WAL). Bulky 5-min facts live as day-partitioned parquet
under `data/raw/<feed>/dt=YYYY-MM-DD.parquet` and are **not** loaded into SQLite unless
`na generate --load-bin-facts` was used. The dashboard/report read the **hourly rollups**.

### Key tables
- `dim_site` (site_id, region, morphology∈{dense_urban,urban,suburban,rural}, lat/lon, backhaul_type∈{fiber,microwave})
- `dim_cell`, `dim_router` (role∈{core,aggregation,pre_aggregation}), `dim_link` (kind∈{access,preagg_uplink,agg_uplink})
- `dim_path_link` (site_id, hop_index 0..2, link_id) — a site's ordered transport path
- `dim_incident` — **ground truth**: incident_class∈{transport,ran,shared}, kind, start/end_ts, magnitude,
  root_entity(_type), affected_site_ids/link_ids/sectors (JSON arrays), auto_generated
- `agg_site_hourly` — the unified KPI panel per (site_id, ts_hour): radio (rsrp_p50, rsrq_p50, prb_util_p95),
  session (tcp_client_rtt_ms, tcp_server_rtt_ms, tcp_fail_pct, retrans_pct, vonr_mos),
  app (dl/ul_throughput_mbps, loaded_latency_ms, youtube_qoe_mos, rebuffer_ratio),
  transport-path (path_delay_ms, path_jitter_ms, path_loss_pct, twamp_*, sevone_*), volumes (sessions, users), availability
- `agg_link_hourly` — per (link_id, ts_hour): util_pct, queue_occ, delay_ms, jitter_ms, loss_pct, discards_pps, crc_rate
- `fact_ookla_test`, `fact_qoe_session` — raw session records (carry true sessions/users impacted)

### Serving / analytics outputs
- `site_scorecard` — rank, impact_score, per-KPI severity_*, sessions/users_impacted, worst_window_*,
  primary_attribution, is_priority (1 = on the Phase-2 audit list)
- `impairment_attribution` — rule_class/confidence/evidence, ml_class/confidence/top_features (SHAP),
  final_class/confidence, matched_incident_id/class (ground truth)
- `anomaly_event`, `incident_detected` (match_iou vs ground truth), `rca_finding` (scope∈{site,incident}),
  `correlation_edge`, `variability_site`
- `gen_run`, `analytics_run` (metrics_json), `job`, `kv_meta` (latest_gen_run / latest_analytics_run)

## KPI meaning & the isolation logic

- **TCP client RTT** = UE↔N3-probe (radio scheduling + full transport path, round trip).
  **TCP server RTT** = probe↔internet server — the site-independent *control*.
- Transport-attributed when radio is normal (RSRP/RSRQ near baseline, PRB not exhausted)
  **and** transport signatures are elevated (TWAMP loss/jitter, SevOne queue/CRC/util,
  path delay/loss, retransmissions, client-RTT up while server-RTT flat) **and** sibling
  sites on the shared pre-agg uplink are also degraded.
- RAN-attributed when RSRP/RSRQ degraded or PRB exhausted, usually single-sector, no transport signature.
- All deviations are robust z-scores vs the site's own **trailing** baseline and its
  morphology+load peer group (`<kpi>__z`, `<kpi>__peer_z` in the feature table).

## Common queries

```sql
-- priority audit list with attributed cause
SELECT s.rank, s.site_id, s.region, s.impact_score, a.final_class, a.final_confidence
FROM site_scorecard s JOIN impairment_attribution a USING(site_id)
WHERE s.is_priority = 1 ORDER BY s.rank;

-- attribution accuracy vs ground truth
SELECT a.final_class, a.matched_incident_class, COUNT(*) n
FROM impairment_attribution a GROUP BY 1,2;

-- a transport link's health and its sibling sites
SELECT h.ts_hour, h.util_pct, h.loss_pct, h.queue_occ
FROM agg_link_hourly h WHERE h.link_id = ? ORDER BY h.ts_hour;
```

Build the analyst feature table in Python with
`networkanalysis.pipeline.features.build_site_feature_table()`.
