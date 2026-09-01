"""Build the analytics report (HTML, optional PDF) and the Phase-2 audit list (xlsx)."""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from networkanalysis.db.database import connect, query_df  # noqa: E402
from networkanalysis.paths import REPORTS_DIR, ensure_dirs  # noqa: E402

TEMPLATES = __import__("pathlib").Path(__file__).parent / "templates"

PALETTE = {"transport": "#e8663c", "ran": "#3b7dd8", "shared": "#8a5cd1", "none": "#8d99a6"}


def _fig_to_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _chart_attribution_mix(scorecard: pd.DataFrame) -> str:
    counts = scorecard[scorecard.is_priority == 1].primary_attribution.value_counts()
    fig, ax = plt.subplots(figsize=(4.2, 3))
    ax.bar(counts.index, counts.values, color=[PALETTE.get(c, "#888") for c in counts.index])
    ax.set_title("Priority sites by attributed cause")
    ax.set_ylabel("sites")
    return _fig_to_uri(fig)


def _chart_top_sites(scorecard: pd.DataFrame) -> str:
    top = scorecard.sort_values("impact_score", ascending=False).head(20)[::-1]
    fig, ax = plt.subplots(figsize=(6.5, 5))
    ax.barh(top.site_id, top.impact_score,
            color=[PALETTE.get(c, "#888") for c in top.primary_attribution])
    ax.set_title("Top 20 sites by impact score")
    ax.set_xlabel("impact score")
    return _fig_to_uri(fig)


def _chart_market_trend(db_path=None) -> str:
    df = query_df(
        "SELECT ts_hour, AVG(tcp_client_rtt_ms) rtt, AVG(dl_throughput_mbps) thr, "
        "AVG(youtube_qoe_mos) yt FROM agg_site_hourly GROUP BY ts_hour ORDER BY ts_hour",
        db_path=db_path,
    )
    df["ts_hour"] = pd.to_datetime(df["ts_hour"])
    fig, axes = plt.subplots(3, 1, figsize=(7, 5.2), sharex=True)
    axes[0].plot(df.ts_hour, df.rtt, color="#e8663c"); axes[0].set_ylabel("TCP RTT ms")
    axes[1].plot(df.ts_hour, df.thr, color="#2f9e6e"); axes[1].set_ylabel("DL Mbps")
    axes[2].plot(df.ts_hour, df.yt, color="#3b7dd8"); axes[2].set_ylabel("YouTube MOS")
    axes[0].set_title("Market KPI trend")
    fig.autofmt_xdate()
    return _fig_to_uri(fig)


def _audit_list(scorecard: pd.DataFrame, attribution: pd.DataFrame, rca: pd.DataFrame) -> pd.DataFrame:
    a = attribution.set_index("site_id")
    site_action = (
        rca[rca.scope == "site"].groupby("scope_id")["recommended_action"].first()
        if len(rca) else pd.Series(dtype=object)
    )
    df = scorecard[scorecard.is_priority == 1].copy().sort_values("rank")
    df["attributed_cause"] = df.site_id.map(a["final_class"])
    df["confidence"] = df.site_id.map(a["final_confidence"])
    df["rule_evidence"] = df.site_id.map(
        lambda s: "; ".join(json.loads(a.loc[s, "rule_evidence"])) if s in a.index and a.loc[s, "rule_evidence"] else ""
    )
    df["recommended_action"] = df.site_id.map(site_action)
    cols = [
        "rank", "site_id", "region", "morphology", "impact_score", "attributed_cause",
        "confidence", "severity_tcp_rtt", "severity_tcp_fail", "severity_throughput",
        "severity_vonr", "severity_youtube", "sessions_impacted", "users_impacted",
        "worst_window_start", "worst_window_end", "rule_evidence", "recommended_action",
    ]
    return df[[c for c in cols if c in df.columns]]


def build_report(fmt: str = "html", db_path=None) -> dict[str, str]:
    ensure_dirs()
    scorecard = query_df("SELECT * FROM site_scorecard", db_path=db_path)
    attribution = query_df("SELECT * FROM impairment_attribution", db_path=db_path)
    rca = query_df("SELECT * FROM rca_finding", db_path=db_path)
    detected = query_df("SELECT * FROM incident_detected", db_path=db_path)
    variability = query_df("SELECT * FROM variability_site", db_path=db_path)
    incidents = query_df("SELECT * FROM dim_incident", db_path=db_path)

    con = connect(db_path)
    try:
        gen = con.execute(
            "SELECT config_json, row_counts_json, preset, n_sites, duration_days, start_date "
            "FROM gen_run ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        an = con.execute(
            "SELECT metrics_json FROM analytics_run ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    metrics = json.loads(an[0]) if an else {}
    attr_eval = (metrics.get("attribution", {}) or {}).get("final_vs_truth_priority") or \
        (metrics.get("attribution", {}) or {}).get("final_vs_truth_all", {})

    audit = _audit_list(scorecard, attribution, rca)
    xlsx_path = REPORTS_DIR / "phase2_audit_list.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
        audit.to_excel(xw, sheet_name="priority_sites", index=False)
        scorecard.sort_values("rank").to_excel(xw, sheet_name="full_scorecard", index=False)
        if len(rca):
            rca.to_excel(xw, sheet_name="rca_findings", index=False)

    priority = scorecard[scorecard.is_priority == 1]
    ctx = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "preset": gen[2] if gen else "?",
        "n_sites": gen[3] if gen else len(scorecard),
        "duration_days": gen[4] if gen else "?",
        "start_date": gen[5] if gen else "?",
        "n_priority": int(priority.shape[0]),
        "mix": priority.primary_attribution.value_counts().to_dict(),
        "attr_eval": attr_eval,
        "anomaly": metrics.get("anomaly", {}),
        "variance_components": metrics.get("variability", {}).get("variance_components", {}),
        "instability_flagged": metrics.get("variability", {}).get("instability_flagged", 0),
        "n_ground_truth": len(incidents),
        "charts": {
            "attribution_mix": _chart_attribution_mix(scorecard),
            "top_sites": _chart_top_sites(scorecard),
            "market_trend": _chart_market_trend(db_path),
        },
        "audit_rows": audit.head(120).to_dict(orient="records"),
        "rca_site": rca[rca.scope == "site"].head(40).to_dict(orient="records") if len(rca) else [],
        "rca_incident": rca[rca.scope == "incident"].to_dict(orient="records") if len(rca) else [],
        "detected": detected.to_dict(orient="records") if len(detected) else [],
        "unstable_sites": variability.sort_values("stability_rank").head(15).to_dict(orient="records")
        if len(variability) else [],
        "xlsx_name": xlsx_path.name,
    }

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape())
    env.filters["pct"] = lambda v: "-" if v is None or v != v else f"{v*100:.0f}%"
    env.filters["r2"] = lambda v: "-" if v is None or v != v else f"{v:.2f}"
    env.filters["fromjson"] = lambda v: json.loads(v) if v else []
    html = env.get_template("report.html.j2").render(**ctx)
    html_path = REPORTS_DIR / "analytics_report.html"
    html_path.write_text(html, encoding="utf-8")

    out = {"html": str(html_path), "xlsx": str(xlsx_path)}
    if fmt in ("pdf", "both"):
        try:
            from weasyprint import HTML  # type: ignore

            pdf_path = REPORTS_DIR / "analytics_report.pdf"
            HTML(string=html).write_pdf(str(pdf_path))
            out["pdf"] = str(pdf_path)
        except Exception as e:  # pragma: no cover
            out["pdf_error"] = f"weasyprint unavailable ({e}); HTML written"
    return out
