"""Run the full analytics engine over the current warehouse and persist serving tables."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from networkanalysis.analytics import anomaly as anom
from networkanalysis.analytics import correlation as corr
from networkanalysis.analytics import rca as rca_mod
from networkanalysis.analytics import scoring as scoring_mod
from networkanalysis.analytics import variability as var_mod
from networkanalysis.analytics.attribution import attribute
from networkanalysis.analytics.groundtruth import load_incidents
from networkanalysis.db.database import connect, insert_dataframe
from networkanalysis.pipeline.features import build_site_feature_table


@dataclass
class AnalyticsResult:
    run_id: str
    seconds: float = 0.0
    n_priority: int = 0
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        fv = m.get("attribution", {}).get("final_vs_truth_priority", {}) or m.get("attribution", {}).get("final_vs_truth_all", {})
        tr = fv.get("transport", {}) if fv else {}
        return (
            f"analytics {self.run_id}: {self.n_priority} priority sites, {self.seconds:.1f}s\n"
            f"  transport attribution (priority): precision={tr.get('precision', float('nan')):.2f} "
            f"recall={tr.get('recall', float('nan')):.2f}  |  "
            f"anomaly incident matches={m.get('anomaly', {}).get('matched_incidents', 0)}"
        )


def _wipe(con, tables):
    for t in tables:
        con.execute(f"DELETE FROM {t}")


def run_analytics(db_path=None, *, on_progress=None) -> AnalyticsResult:
    t0 = time.time()
    run_id = datetime.now(UTC).strftime("an_%Y%m%dT%H%M%S")

    def rep(stage, pct, msg=""):
        if on_progress:
            on_progress(stage, pct, msg)

    rep("features", 0.05, "building site feature table")
    feat = build_site_feature_table(db_path)
    incidents = load_incidents(db_path)
    metrics: dict = {}

    rep("scoring", 0.2, "impact scoring & ranking")
    scorecard, _ = scoring_mod.compute_scorecard(feat)
    n_priority = int(scorecard.is_priority.sum())

    rep("attribution", 0.35, "transport vs RAN attribution (rules + ML + SHAP)")
    attribution, attr_report = attribute(feat, incidents, scorecard, db_path)
    metrics["attribution"] = attr_report
    amap = attribution.set_index("site_id")
    scorecard["primary_attribution"] = scorecard.site_id.map(amap["final_class"]).fillna("none")
    scorecard["attribution_confidence"] = scorecard.site_id.map(amap["final_confidence"]).fillna(0.0)

    rep("correlation", 0.5, "correlation & driver analysis")
    corr_edges = corr.compute_correlations(feat, scorecard)
    driver = corr.layer_driver_split(feat, scorecard)
    metrics["correlation"] = {
        "edges": int(len(corr_edges)),
        "median_transport_share": float(driver.transport_share.median()) if len(driver) else None,
    }

    rep("anomaly", 0.62, "anomaly detection (STL + IsolationForest + PELT)")
    uni = anom.univariate_anomalies(feat, scorecard=scorecard)
    mv = anom.multivariate_anomalies(feat, scorecard)
    all_anom = pd.concat([uni, mv], ignore_index=True) if len(uni) or len(mv) else pd.DataFrame()
    detected = anom.cluster_incidents(all_anom, db_path)
    matched = int((detected["match_iou"] > 0.2).sum()) if len(detected) else 0
    metrics["anomaly"] = {
        "univariate_events": int(len(uni)), "multivariate_events": int(len(mv)),
        "detected_incidents": int(len(detected)), "matched_incidents": matched,
        "ground_truth_incidents": int(len(incidents)),
    }

    rep("variability", 0.75, "variability analysis")
    variability = var_mod.compute_variability(feat)
    metrics["variability"] = {
        "instability_flagged": int(variability.instability_flag.sum()) if len(variability) else 0,
        "variance_components": var_mod.variance_components_market(feat),
    }

    rep("rca", 0.85, "root-cause analysis")
    findings = rca_mod.build_rca(feat, scorecard, attribution, detected, db_path)

    rep("persist", 0.93, "writing serving tables")
    con = connect(db_path, fast=True)
    try:
        _wipe(con, [
            "site_scorecard", "impairment_attribution", "anomaly_event", "incident_detected",
            "rca_finding", "correlation_edge", "variability_site",
        ])
        sc_cols = [
            "site_id", "region", "morphology", "rank", "impact_score",
            "severity_tcp_rtt", "severity_tcp_fail", "severity_throughput", "severity_vonr", "severity_youtube",
            "sessions_impacted", "users_impacted", "worst_window_start", "worst_window_end",
            "primary_attribution", "attribution_confidence", "is_priority",
        ]
        rename = {"severity_tcp_rtt": "severity_tcp_rtt"}
        sc = scorecard.rename(columns=rename)
        for c in sc_cols:
            if c not in sc.columns:
                sc[c] = None
        insert_dataframe(con, "site_scorecard", sc[sc_cols])

        attribution2 = attribution.copy()
        attribution2["final_class"] = attribution2["final_class"]
        insert_dataframe(con, "impairment_attribution", attribution2.rename(columns={
            "final_class": "final_class", "final_confidence": "final_confidence"
        })[[
            "site_id", "rule_class", "rule_confidence", "rule_evidence", "ml_class", "ml_confidence",
            "ml_top_features", "final_class", "final_confidence", "matched_incident_id", "matched_incident_class",
        ]])

        if len(all_anom):
            insert_dataframe(con, "anomaly_event", all_anom)
        if len(detected):
            insert_dataframe(con, "incident_detected", detected)
        if len(findings):
            insert_dataframe(con, "rca_finding", findings)
        if len(corr_edges):
            insert_dataframe(con, "correlation_edge", corr_edges)
        if len(variability):
            vcols = ["site_id", "metric", "cv", "iqr", "busy_offpeak_ratio", "within_day_var",
                     "day_to_day_var", "stability_rank", "instability_flag", "wow_psi", "wow_shift"]
            insert_dataframe(con, "variability_site", variability[vcols])

        con.execute(
            "INSERT OR REPLACE INTO analytics_run (run_id, created_at, gen_run_id, metrics_json) VALUES (?,?,?,?)",
            (run_id, datetime.now(UTC).isoformat(),
             con.execute("SELECT v FROM kv_meta WHERE k='latest_gen_run'").fetchone()[0]
             if con.execute("SELECT v FROM kv_meta WHERE k='latest_gen_run'").fetchone() else None,
             json.dumps(metrics, default=str)),
        )
        con.execute("INSERT OR REPLACE INTO kv_meta (k, v) VALUES ('latest_analytics_run', ?)", (run_id,))
        con.execute("INSERT OR REPLACE INTO kv_meta (k, v) VALUES ('driver_split', ?)", (driver.to_json(orient="records"),))
    finally:
        con.close()

    rep("done", 1.0, "analytics complete")
    return AnalyticsResult(run_id=run_id, seconds=time.time() - t0, n_priority=n_priority, metrics=metrics)
