"""Orchestrate a full synthetic-data generation run.

topology -> incidents (ground truth) -> causal metric model -> raw sessions -> hourly
rollups -> load everything into the SQLite warehouse -> record the run.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from networkanalysis.config.models import GenConfig
from networkanalysis.db.database import connect, insert_dataframe, load_parquet_glob, reset_db
from networkanalysis.generate.incidents import schedule_incidents
from networkanalysis.generate.model import run_model
from networkanalysis.generate.rollup import build_rollups
from networkanalysis.generate.sessions import generate_sessions
from networkanalysis.generate.timeprofile import build_time_index
from networkanalysis.paths import RAW_DIR, WAREHOUSE_DB, ensure_dirs
from networkanalysis.topology.generate import build_topology


@dataclass
class GenerationResult:
    run_id: str
    n_sites: int
    n_links: int
    n_incidents: int
    row_counts: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    def summary(self) -> str:
        rc = ", ".join(f"{k}={v:,}" for k, v in sorted(self.row_counts.items()) if v)
        return (
            f"run {self.run_id}: {self.n_sites} sites, {self.n_links} links, "
            f"{self.n_incidents} incidents, {self.seconds:.1f}s\n  {rc}"
        )


def run_generation(cfg: GenConfig, *, on_progress=None, clean_raw: bool = True,
                   load_bin_facts: bool = False) -> GenerationResult:
    ensure_dirs()
    t0 = time.time()
    run_id = datetime.now(UTC).strftime("gen_%Y%m%dT%H%M%S")

    def report(stage: str, pct: float, msg: str = "") -> None:
        if on_progress:
            on_progress(stage, pct, msg)

    if clean_raw and RAW_DIR.exists():
        shutil.rmtree(RAW_DIR)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    report("topology", 0.02, "building market + transport graph")
    topo = build_topology(cfg.market, cfg.topology_seed)

    ts_index = build_time_index(cfg.start_date, cfg.n_bins, cfg.bin_seconds)

    report("incidents", 0.06, "scheduling labelled incidents")
    inc_df = schedule_incidents(cfg, topo, ts_index)

    report("model", 0.10, "running causal metric model")
    n_days = cfg.duration_days

    def model_prog(day, done):
        report("model", 0.10 + 0.45 * done / max(n_days, 1), f"metrics day {done}/{n_days} ({day})")

    mout = run_model(cfg, topo, inc_df, ts_index, RAW_DIR, progress=model_prog)

    report("sessions", 0.56, "synthesising raw Ookla / QoE sessions")

    def sess_prog(day, done):
        report("sessions", 0.56 + 0.14 * done / max(n_days, 1), f"sessions day {done}/{n_days}")

    sess_files = generate_sessions(cfg, topo, mout.files["site_bin"], RAW_DIR, progress=sess_prog)

    report("rollup", 0.72, "building hourly serving rollups")
    rollups = build_rollups(
        topo, mout.files["site_bin"], mout.files["link_bin"], mout.files["twamp_5min"], mout.files["sevone_5min"],
        progress=lambda msg, frac: report("rollup", 0.72 + 0.06 * frac, msg),
    )

    report("load", 0.80, "loading SQLite warehouse")
    reset_db(WAREHOUSE_DB)
    con = connect(WAREHOUSE_DB, fast=True)
    counts: dict[str, int] = {}
    try:
        for name, df in topo.tables().items():
            counts[name] = insert_dataframe(con, name, df)
        counts["dim_incident"] = insert_dataframe(con, "dim_incident", inc_df)

        # 5-min bin facts stay as parquet by default (notebooks read them directly); the
        # dashboard + analytics read the hourly rollups. Pass load_bin_facts=True to also
        # load them into SQLite for SQL drill-down.
        fact_map = {
            "fact_ookla_test": sess_files.get("ookla_test", []),
            "fact_qoe_session": sess_files.get("qoe_session", []),
        }
        if load_bin_facts:
            fact_map.update({
                "fact_site_bin": mout.files["site_bin"],
                "fact_link_bin": mout.files["link_bin"],
                "fact_twamp_5min": mout.files["twamp_5min"],
                "fact_sevone_5min": mout.files["sevone_5min"],
                "fact_n3_5min": mout.files["n3_5min"],
            })
        for i, (table, files) in enumerate(fact_map.items()):
            counts[table] = load_parquet_glob(con, table, files)
            report("load", 0.80 + 0.13 * (i + 1) / len(fact_map), f"loaded {table}")

        for name, df in rollups.items():
            counts[name] = insert_dataframe(con, name, df)

        row_counts_json = json.dumps(counts)
        con.execute(
            "INSERT OR REPLACE INTO gen_run (run_id, created_at, preset, seed, topology_seed, "
            "start_date, duration_days, bin_seconds, n_sites, n_links, n_incidents, config_json, row_counts_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, datetime.now(UTC).isoformat(), cfg.name, cfg.seed, cfg.topology_seed,
                str(cfg.start_date), cfg.duration_days, cfg.bin_seconds,
                topo.n_sites, len(topo.links), len(inc_df),
                json.dumps(cfg.to_yaml_dict(), default=str), row_counts_json,
            ),
        )
        con.execute("INSERT OR REPLACE INTO kv_meta (k, v) VALUES ('latest_gen_run', ?)", (run_id,))
        con.execute("PRAGMA optimize")
    finally:
        con.close()

    report("done", 1.0, "generation complete")
    return GenerationResult(
        run_id=run_id,
        n_sites=topo.n_sites,
        n_links=len(topo.links),
        n_incidents=len(inc_df),
        row_counts=counts,
        seconds=time.time() - t0,
    )
