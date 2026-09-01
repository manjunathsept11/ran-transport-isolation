"""Very small background-job runner for long tasks (generation, analytics, report).

A single worker thread drains a queue; job state lives in the ``job`` table so the UI can
poll ``GET /api/jobs/{id}``. No Redis/Celery - this is a standalone single-node app.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import UTC, datetime
from queue import Queue

from networkanalysis.db.database import connect

_queue: Queue[tuple[str, str, dict]] = Queue()
_worker_started = False
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _update(job_id: str, **fields) -> None:
    fields.setdefault("updated_at", _now())
    sets = ", ".join(f"{k}=?" for k in fields)
    con = connect()
    try:
        con.execute(f"UPDATE job SET {sets} WHERE job_id=?", (*fields.values(), job_id))
    finally:
        con.close()


def create_job(kind: str, params: dict) -> str:
    job_id = f"{kind}_{uuid.uuid4().hex[:10]}"
    con = connect()
    try:
        con.execute(
            "INSERT INTO job (job_id, kind, status, progress, message, created_at, updated_at, params_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (job_id, kind, "queued", 0.0, "queued", _now(), _now(), json.dumps(params)),
        )
    finally:
        con.close()
    _queue.put((job_id, kind, params))
    _ensure_worker()
    return job_id


def get_job(job_id: str) -> dict | None:
    con = connect()
    try:
        cur = con.execute("SELECT * FROM job WHERE job_id=?", (job_id,))
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    finally:
        con.close()
    if not row:
        return None
    d = dict(zip(cols, row))
    for k in ("params_json", "result_json"):
        if d.get(k):
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
            except Exception:
                pass
    return d


def recent_jobs(limit: int = 20) -> list[dict]:
    con = connect()
    try:
        cur = con.execute(
            "SELECT job_id, kind, status, progress, message, created_at, updated_at "
            "FROM job ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    finally:
        con.close()
    return [dict(zip(cols, r)) for r in rows]


def _run(job_id: str, kind: str, params: dict) -> None:
    def progress(stage, pct, msg=""):
        _update(job_id, status="running", progress=round(float(pct), 4), message=f"{stage}: {msg}")

    _update(job_id, status="running", progress=0.0, message="starting")
    try:
        if kind == "generate":
            from networkanalysis.config.models import GenConfig
            from networkanalysis.config.presets import load_config
            from networkanalysis.generate import run_generation

            if params.get("config"):
                cfg = GenConfig.model_validate(params["config"])
            else:
                cfg = load_config(params.get("preset", "mixed_realistic"))
            for key in ("seed", "duration_days"):
                if params.get(key):
                    setattr(cfg, key, params[key])
            if params.get("n_sites"):
                cfg.market.n_sites = int(params["n_sites"])
            do_analytics = params.get("run_analytics", True)
            gen_span = 0.6 if do_analytics else 1.0
            res = run_generation(cfg, on_progress=lambda s, p, m: progress(s, p * gen_span, m))
            result = {"run_id": res.run_id, "row_counts": res.row_counts, "seconds": res.seconds,
                      "n_incidents": res.n_incidents}
            if do_analytics:
                from networkanalysis.analytics import run_analytics

                ares = run_analytics(on_progress=lambda s, p, m: progress(s, 0.6 + 0.4 * p, m))
                result["analytics_run_id"] = ares.run_id
                result["analytics_metrics"] = ares.metrics
        elif kind == "analytics":
            from networkanalysis.analytics import run_analytics

            ares = run_analytics(on_progress=progress)
            result = {"run_id": ares.run_id, "metrics": ares.metrics, "seconds": ares.seconds}
        elif kind == "report":
            from networkanalysis.report import build_report

            result = build_report(fmt=params.get("fmt", "html"))
        else:
            raise ValueError(f"unknown job kind {kind}")
        _update(job_id, status="done", progress=1.0, message="complete",
                result_json=json.dumps(result, default=str))
    except Exception as e:  # pragma: no cover
        _update(job_id, status="error", message=str(e),
                result_json=json.dumps({"error": str(e), "trace": traceback.format_exc()}))


def _worker_loop() -> None:
    while True:
        job_id, kind, params = _queue.get()
        try:
            _run(job_id, kind, params)
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if not _worker_started:
            threading.Thread(target=_worker_loop, daemon=True, name="na-jobs").start()
            _worker_started = True
