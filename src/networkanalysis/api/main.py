"""FastAPI backend for the RAN & Transport Isolation dashboard."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from networkanalysis.api import jobs
from networkanalysis.config.models import GenConfig
from networkanalysis.config.presets import list_presets, load_config, save_preset
from networkanalysis.db.database import connect, query_df
from networkanalysis.paths import REPORTS_DIR, WAREHOUSE_DB


def _clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(_clean(content), ensure_ascii=False, default=str).encode("utf-8")

app = FastAPI(title="RAN & Transport Isolation API", version="0.1.0",
              default_response_class=SafeJSONResponse)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _has_data() -> bool:
    if not Path(WAREHOUSE_DB).exists():
        return False
    con = connect()
    try:
        return con.execute("SELECT COUNT(*) FROM dim_site").fetchone()[0] > 0
    except Exception:
        return False
    finally:
        con.close()


def _meta(key: str):
    con = connect()
    try:
        row = con.execute("SELECT v FROM kv_meta WHERE k=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


# ------------------------------------------------------------------ status
@app.get("/api/status")
def status():
    if not _has_data():
        return {"has_data": False}
    con = connect()
    try:
        gen = con.execute(
            "SELECT run_id, preset, n_sites, n_links, n_incidents, duration_days, start_date, "
            "created_at, row_counts_json FROM gen_run ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        an = con.execute(
            "SELECT run_id, created_at, metrics_json FROM analytics_run ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    return {
        "has_data": True,
        "generation": {
            "run_id": gen[0], "preset": gen[1], "n_sites": gen[2], "n_links": gen[3],
            "n_incidents": gen[4], "duration_days": gen[5], "start_date": gen[6],
            "created_at": gen[7], "row_counts": json.loads(gen[8] or "{}"),
        } if gen else None,
        "analytics": {
            "run_id": an[0], "created_at": an[1], "metrics": json.loads(an[2] or "{}"),
        } if an else None,
    }


# ------------------------------------------------------------------ overview
@app.get("/api/overview")
def overview():
    if not _has_data():
        raise HTTPException(404, "no data - run a generation first")
    sc = query_df("SELECT * FROM site_scorecard")
    sites = query_df("SELECT site_id, region, morphology, lat, lon, backhaul_type FROM dim_site")
    m = sites.merge(sc, on=["site_id", "region", "morphology"], how="left")
    m["impact_score"] = m["impact_score"].fillna(0.0)
    m["is_priority"] = m["is_priority"].fillna(0).astype(int)
    m["primary_attribution"] = m["primary_attribution"].fillna("none")
    trend = query_df(
        "SELECT ts_hour, ROUND(AVG(tcp_client_rtt_ms),2) tcp_rtt, ROUND(AVG(tcp_fail_pct),3) tcp_fail, "
        "ROUND(AVG(dl_throughput_mbps),2) dl_mbps, ROUND(AVG(vonr_mos),3) vonr_mos, "
        "ROUND(AVG(youtube_qoe_mos),3) youtube_mos FROM agg_site_hourly GROUP BY ts_hour ORDER BY ts_hour"
    )
    prio = sc[sc.is_priority == 1]
    kpi_now = trend.tail(24).mean(numeric_only=True).round(3).to_dict() if len(trend) else {}
    kpi_base = trend.head(24).mean(numeric_only=True).round(3).to_dict() if len(trend) else {}
    return {
        "sites": m[["site_id", "region", "morphology", "lat", "lon", "backhaul_type",
                    "impact_score", "is_priority", "primary_attribution", "rank"]].to_dict("records"),
        "trend": trend.to_dict("records"),
        "kpi_now": kpi_now,
        "kpi_baseline": kpi_base,
        "summary": {
            "n_sites": int(len(sites)),
            "n_priority": int(len(prio)),
            "attribution_mix": prio.primary_attribution.value_counts().to_dict(),
            "sessions_impacted": float(prio.sessions_impacted.sum()),
            "users_impacted": float(prio.users_impacted.sum()),
        },
    }


# ------------------------------------------------------------------ scorecard / priority list
@app.get("/api/scorecard")
def scorecard(priority_only: bool = False):
    if not _has_data():
        raise HTTPException(404, "no data")
    q = "SELECT s.*, a.rule_evidence, a.ml_top_features, a.rule_class, a.ml_class, a.final_confidence " \
        "FROM site_scorecard s LEFT JOIN impairment_attribution a USING(site_id)"
    if priority_only:
        q += " WHERE s.is_priority=1"
    q += " ORDER BY s.rank"
    df = query_df(q)
    for c in ("rule_evidence", "ml_top_features"):
        df[c] = df[c].apply(lambda v: json.loads(v) if isinstance(v, str) and v else [])
    return df.to_dict("records")


# ------------------------------------------------------------------ site detail
@app.get("/api/sites/{site_id}")
def site_detail(site_id: str):
    if not _has_data():
        raise HTTPException(404, "no data")
    dim = query_df("SELECT * FROM dim_site WHERE site_id=?", (site_id,))
    if dim.empty:
        raise HTTPException(404, f"unknown site {site_id}")
    hourly = query_df("SELECT * FROM agg_site_hourly WHERE site_id=? ORDER BY ts_hour", (site_id,))
    sc = query_df("SELECT * FROM site_scorecard WHERE site_id=?", (site_id,))
    attr = query_df("SELECT * FROM impairment_attribution WHERE site_id=?", (site_id,))
    anoms = query_df(
        "SELECT * FROM anomaly_event WHERE entity_type='site' AND entity_id=? ORDER BY start_ts", (site_id,)
    )
    rca = query_df("SELECT * FROM rca_finding WHERE scope='site' AND scope_id=?", (site_id,))
    corr = query_df("SELECT * FROM correlation_edge WHERE scope='site' AND scope_id=?", (site_id,))
    var = query_df("SELECT * FROM variability_site WHERE site_id=?", (site_id,))
    path = query_df(
        "SELECT p.hop_index, p.link_id, l.kind, l.media, l.capacity_mbps, l.endpoint_a, l.endpoint_b "
        "FROM dim_path_link p JOIN dim_link l ON l.link_id=p.link_id WHERE p.site_id=? ORDER BY p.hop_index",
        (site_id,),
    )
    incidents = query_df("SELECT * FROM dim_incident")
    inc = []
    for _, r in incidents.iterrows():
        if site_id in json.loads(r.affected_site_ids or "[]"):
            inc.append({"incident_id": r.incident_id, "class": r.incident_class, "kind": r.kind,
                        "start_ts": r.start_ts, "end_ts": r.end_ts, "magnitude": r.magnitude,
                        "root_entity": r.root_entity})

    def js(df, cols=("rule_evidence", "ml_top_features")):
        rec = df.to_dict("records")
        for row in rec:
            for c in cols:
                if isinstance(row.get(c), str) and row[c]:
                    try:
                        row[c] = json.loads(row[c])
                    except Exception:
                        pass
        return rec

    return {
        "site": dim.iloc[0].to_dict(),
        "scorecard": sc.iloc[0].to_dict() if len(sc) else None,
        "attribution": js(attr)[0] if len(attr) else None,
        "hourly": hourly.to_dict("records"),
        "anomalies": anoms.to_dict("records"),
        "rca": js(rca, ("evidence",)),
        "correlations": corr.to_dict("records"),
        "variability": var.iloc[0].to_dict() if len(var) else None,
        "path": path.to_dict("records"),
        "ground_truth_incidents": inc,
    }


# ------------------------------------------------------------------ transport paths / links
@app.get("/api/links")
def links():
    if not _has_data():
        raise HTTPException(404, "no data")
    df = query_df(
        "SELECT l.*, "
        "(SELECT COUNT(DISTINCT p.site_id) FROM dim_path_link p WHERE p.link_id=l.link_id) site_count, "
        "h.util_pct, h.loss_pct, h.delay_ms, h.jitter_ms, h.queue_occ "
        "FROM dim_link l LEFT JOIN ("
        "  SELECT link_id, AVG(util_pct) util_pct, MAX(loss_pct) loss_pct, MAX(delay_ms) delay_ms, "
        "  MAX(jitter_ms) jitter_ms, MAX(queue_occ) queue_occ FROM agg_link_hourly GROUP BY link_id"
        ") h ON h.link_id=l.link_id ORDER BY h.loss_pct DESC"
    )
    return df.to_dict("records")


@app.get("/api/links/{link_id}")
def link_detail(link_id: str):
    if not _has_data():
        raise HTTPException(404, "no data")
    link = query_df("SELECT * FROM dim_link WHERE link_id=?", (link_id,))
    if link.empty:
        raise HTTPException(404, f"unknown link {link_id}")
    hourly = query_df("SELECT * FROM agg_link_hourly WHERE link_id=? ORDER BY ts_hour", (link_id,))
    siblings = query_df(
        "SELECT s.site_id, s.impact_score, s.primary_attribution, s.is_priority, s.rank "
        "FROM dim_path_link p JOIN site_scorecard s ON s.site_id=p.site_id WHERE p.link_id=? "
        "ORDER BY s.impact_score DESC", (link_id,)
    )
    return {
        "link": link.iloc[0].to_dict(),
        "hourly": hourly.to_dict("records"),
        "sibling_sites": siblings.to_dict("records"),
    }


# ------------------------------------------------------------------ incidents / anomalies / rca
@app.get("/api/incidents")
def incidents():
    if not _has_data():
        raise HTTPException(404, "no data")
    detected = query_df("SELECT * FROM incident_detected ORDER BY severity DESC")
    gt = query_df("SELECT * FROM dim_incident ORDER BY start_ts")
    rca = query_df("SELECT * FROM rca_finding WHERE scope='incident'")
    for df, cols in ((detected, ("site_ids", "link_ids")), (gt, ("affected_site_ids", "affected_link_ids", "affected_sectors")), (rca, ("evidence",))):
        for c in cols:
            if c in df.columns:
                df[c] = df[c].apply(lambda v: json.loads(v) if isinstance(v, str) and v else [])
    return {
        "detected": detected.to_dict("records"),
        "ground_truth": gt.to_dict("records"),
        "rca": rca.to_dict("records"),
    }


@app.get("/api/anomalies")
def anomalies():
    if not _has_data():
        raise HTTPException(404, "no data")
    df = query_df(
        "SELECT a.*, s.impact_score, s.region, s.morphology FROM anomaly_event a "
        "LEFT JOIN site_scorecard s ON s.site_id=a.entity_id ORDER BY a.start_ts"
    )
    return df.to_dict("records")


@app.get("/api/variability")
def variability():
    if not _has_data():
        raise HTTPException(404, "no data")
    df = query_df(
        "SELECT v.*, s.impact_score, s.region, s.morphology, s.primary_attribution "
        "FROM variability_site v LEFT JOIN site_scorecard s USING(site_id) ORDER BY v.stability_rank"
    )
    driver = json.loads(_meta("driver_split") or "[]")
    return {"sites": df.to_dict("records"), "drivers": driver}


@app.get("/api/correlations")
def correlations():
    if not _has_data():
        raise HTTPException(404, "no data")
    return query_df("SELECT * FROM correlation_edge WHERE scope='market'").to_dict("records")


# ------------------------------------------------------------------ config / presets / jobs
class GenerateRequest(BaseModel):
    preset: str | None = "mixed_realistic"
    n_sites: int | None = None
    duration_days: int | None = None
    seed: int | None = None
    config: dict | None = None
    run_analytics: bool = True


@app.get("/api/presets")
def presets():
    out = []
    for name in list_presets():
        try:
            cfg = load_config(name)
            out.append({"name": name, "description": cfg.description.strip(),
                        "n_sites": cfg.market.n_sites, "duration_days": cfg.duration_days,
                        "n_incidents": len(cfg.incidents)})
        except Exception as e:
            out.append({"name": name, "error": str(e)})
    return out


@app.get("/api/config/{preset}")
def get_config(preset: str):
    try:
        return load_config(preset).model_dump(mode="json", by_alias=True)
    except FileNotFoundError as e:
        raise HTTPException(404, f"preset {preset} not found") from e


class SavePresetRequest(BaseModel):
    name: str
    config: dict


@app.post("/api/config")
def post_config(req: SavePresetRequest):
    cfg = GenConfig.model_validate(req.config)
    cfg.name = req.name
    path = save_preset(cfg, req.name)
    return {"saved": str(path), "name": req.name}


@app.get("/api/config-schema")
def config_schema():
    return GenConfig.model_json_schema(by_alias=True)


@app.post("/api/jobs/generate")
def start_generate(req: GenerateRequest):
    return {"job_id": jobs.create_job("generate", req.model_dump())}


@app.post("/api/jobs/analytics")
def start_analytics():
    return {"job_id": jobs.create_job("analytics", {})}


@app.post("/api/jobs/report")
def start_report(fmt: str = "html"):
    return {"job_id": jobs.create_job("report", {"fmt": fmt})}


@app.get("/api/jobs")
def all_jobs():
    return jobs.recent_jobs()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    j = jobs.get_job(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return j


@app.get("/api/report")
def report_file():
    p = REPORTS_DIR / "analytics_report.html"
    if not p.exists():
        raise HTTPException(404, "no report built yet")
    return FileResponse(p)


@app.get("/api/report/audit.xlsx")
def audit_file():
    p = REPORTS_DIR / "phase2_audit_list.xlsx"
    if not p.exists():
        raise HTTPException(404, "no audit list built yet")
    return FileResponse(p, filename="phase2_audit_list.xlsx")


# ------------------------------------------------------------------ static (built dashboard)
_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
