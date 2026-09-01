"""Fast smoke tests over a tiny generated dataset (shared across the module)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from networkanalysis.analytics import run_analytics
from networkanalysis.analytics.groundtruth import classification_report
from networkanalysis.config.models import Distribution, GenConfig, IncidentSpec
from networkanalysis.config.presets import builtin_preset_names, load_preset
from networkanalysis.db.database import query_df, table_counts
from networkanalysis.generate import run_generation
from networkanalysis.topology.generate import build_topology


@pytest.fixture(scope="session")
def dataset():
    cfg = load_preset("mixed_realistic")
    cfg.market.n_sites = 90
    cfg.duration_days = 5
    cfg.seed = 999
    res = run_generation(cfg)
    an = run_analytics()
    return res, an


# ------------------------------------------------------------- unit-ish
def test_distribution_validation():
    with pytest.raises(ValueError):
        Distribution(kind="normal", params={"mean": 1.0})  # missing sd
    d = Distribution(kind="lognormal", params={"mean": 5.0, "sigma": 0.5}, clip_min=0)
    s = d.sample(np.random.default_rng(0), 1000)
    assert (s >= 0).all() and 2 < np.median(s) < 12


def test_incident_class_kind_guard():
    with pytest.raises(ValueError):
        IncidentSpec(**{"class": "ran"}, kind="microwave_fade")  # kind is a transport kind


def test_all_builtin_presets_load():
    for name in builtin_preset_names():
        cfg = load_preset(name)
        assert isinstance(cfg, GenConfig)
        assert cfg.n_bins > 0


def test_topology_paths_are_shared():
    topo = build_topology(load_preset("mixed_realistic").market.model_copy(update={"n_sites": 120}), seed=1)
    # every site has a 3-hop path and pre-agg uplinks carry many sites
    assert (topo.path_links.groupby("site_id").size() == 3).all()
    up = topo.links[topo.links.kind == "preagg_uplink"].link_id
    carried = topo.path_links[topo.path_links.link_id.isin(up)].groupby("link_id").size()
    assert carried.max() > 5


# ------------------------------------------------------------- integration
def test_warehouse_populated(dataset):
    counts = table_counts()
    for t in ("dim_site", "dim_link", "dim_incident", "agg_site_hourly",
              "fact_ookla_test", "site_scorecard", "impairment_attribution"):
        assert counts.get(t, 0) > 0, t


def test_kpi_ranges_plausible(dataset):
    df = query_df("SELECT * FROM agg_site_hourly")
    assert df.tcp_client_rtt_ms.between(1, 3000).mean() > 0.99
    assert df.vonr_mos.between(1, 4.6).mean() > 0.99
    assert df.dl_throughput_mbps.gt(0).mean() > 0.99
    assert -130 < df.rsrp_p50.median() < -70


def test_cross_kpi_correlation_signs(dataset):
    df = query_df(
        "SELECT tcp_client_rtt_ms, dl_throughput_mbps, sevone_queue_depth FROM agg_site_hourly"
    ).dropna()
    # more queue -> higher RTT -> lower throughput
    assert df.sevone_queue_depth.corr(df.tcp_client_rtt_ms) > 0.05
    assert df.tcp_client_rtt_ms.corr(df.dl_throughput_mbps) < 0.0


def test_attribution_beats_baseline(dataset):
    _, an = dataset
    ev = an.metrics["attribution"].get("final_vs_truth_all", {})
    assert ev.get("accuracy", 0) >= 0.75
    tr = ev.get("transport", {})
    assert tr.get("recall", 0) >= 0.6


def test_scorecard_priority_slice(dataset):
    sc = query_df("SELECT * FROM site_scorecard")
    assert sc.is_priority.sum() >= 60
    assert sc["rank"].is_monotonic_increasing
    assert sc.loc[sc.is_priority == 1, "impact_score"].min() >= sc.loc[sc.is_priority == 0, "impact_score"].max() - 1e-6


def test_report_builds(dataset, tmp_path):
    from networkanalysis.report import build_report

    out = build_report(fmt="html")
    assert out["html"].endswith(".html")
    assert out["xlsx"].endswith(".xlsx")


def test_classification_report_shape():
    import pandas as pd

    r = classification_report(pd.Series(["transport", "none", "ran", "none"]),
                              pd.Series(["transport", "none", "none", "none"]))
    assert r["accuracy"] == 0.75
    assert "transport" in r
