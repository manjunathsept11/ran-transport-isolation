"""End-to-end verification: generator determinism + ground-truth recovery targets."""

from __future__ import annotations

import json

import pandas as pd

from networkanalysis.analytics import run_analytics
from networkanalysis.config.presets import load_config
from networkanalysis.db.database import query_df
from networkanalysis.generate import run_generation


def _checksum() -> dict:
    out = {}
    for t in ("dim_site", "dim_link", "dim_incident", "agg_site_hourly", "fact_ookla_test"):
        df = query_df(f"SELECT * FROM {t}")
        out[t] = (len(df), int(pd.util.hash_pandas_object(df.round(3), index=False).sum() % (10**12)))
    return out


def run_verification(console=None) -> bool:
    def say(msg, ok=None):
        mark = "" if ok is None else ("[green]PASS[/] " if ok else "[red]FAIL[/] ")
        (console.print if console else print)(f"{mark}{msg}")

    cfg = load_config("mixed_realistic")
    cfg.market.n_sites = 120
    cfg.duration_days = 6
    cfg.seed = 12345

    say("run 1 …")
    run_generation(cfg)
    c1 = _checksum()
    say("run 2 (same seed) …")
    run_generation(cfg)
    c2 = _checksum()
    deterministic = c1 == c2
    say(f"generator determinism (identical checksums): {c1 == c2}", deterministic)

    say("analytics …")
    res = run_analytics()
    m = res.metrics
    attr = m["attribution"]
    ev = attr.get("final_vs_truth_priority") or attr.get("final_vs_truth_all", {})
    tr = ev.get("transport", {})
    anom = m["anomaly"]

    checks = [
        ("transport-class recall >= 0.70", tr.get("recall", 0) >= 0.70),
        ("transport-class precision >= 0.55", tr.get("precision", 0) >= 0.55),
        ("overall attribution accuracy >= 0.80", ev.get("accuracy", 0) >= 0.80),
        (
            "anomaly detector matched >= 25% of ground-truth incidents",
            anom.get("matched_incidents", 0) >= max(1, 0.25 * anom.get("ground_truth_incidents", 1)),
        ),
        ("at least one transport incident localised in RCA",
         len(query_df("SELECT 1 FROM rca_finding WHERE scope='incident' AND cause_class='transport'")) >= 1),
    ]
    allok = deterministic
    for name, ok in checks:
        say(name, ok)
        allok = allok and ok

    say(json.dumps({"transport": tr, "accuracy": ev.get("accuracy"), "anomaly": anom}, indent=1, default=str))
    say(("ALL CHECKS PASSED" if allok else "SOME CHECKS FAILED"), allok)
    return allok
