"""Generate the analysis notebooks as .ipynb files.

Run:  python notebooks/_build_notebooks.py
Keeps the notebook content version-controlled as plain Python here; the .ipynb files are
the runnable artefacts analysts open in JupyterLab.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent


def nb(*cells):
    out = []
    for kind, src in cells:
        src_lines = src.strip("\n").splitlines(keepends=True)
        if kind == "md":
            out.append({"cell_type": "markdown", "metadata": {}, "source": src_lines})
        else:
            out.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                        "outputs": [], "source": src_lines})
    return {
        "cells": out,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


SETUP = """
import pandas as pd, numpy as np, matplotlib.pyplot as plt
pd.set_option("display.max_columns", 60)
from networkanalysis.db.database import query_df, table_counts
from networkanalysis.pipeline.features import build_site_feature_table, KPI_DIRECTION, HEADLINE_KPIS
"""

NOTEBOOKS = {
"00_setup_and_data_dictionary": nb(
    ("md", "# 00 · Setup & data dictionary\nConnect to the SQLite warehouse and tour the schema."),
    ("code", SETUP),
    ("code", "table_counts()"),
    ("code", """
# schema
con_tables = query_df("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for t in con_tables.name:
    cols = query_df(f"PRAGMA table_info({t})")
    print(f"\\n### {t}")
    print(", ".join(cols.name + " (" + cols.type + ")"))
"""),
    ("code", """
# KPI direction reference (+1 = higher is worse)
pd.Series(KPI_DIRECTION, name="direction").to_frame()
"""),
    ("code", """
# the latest generation config
import json
cfg = query_df("SELECT config_json FROM gen_run ORDER BY created_at DESC LIMIT 1").iloc[0,0]
print(json.dumps(json.loads(cfg), indent=2)[:2000])
"""),
),

"01_eda_overview": nb(
    ("md", "# 01 · EDA overview\nVolumes, coverage, missingness, KPI distributions, diurnal / weekly shape."),
    ("code", SETUP),
    ("code", "feat = build_site_feature_table(); feat.shape"),
    ("code", """
# volumes & missingness
print(query_df("SELECT COUNT(*) hours, COUNT(DISTINCT site_id) sites, MIN(ts_hour) t0, MAX(ts_hour) t1 FROM agg_site_hourly"))
feat[list(HEADLINE_KPIS)].describe().T
"""),
    ("code", """
# diurnal shape of the headline KPIs
g = feat.assign(hour=feat.ts_hour.dt.hour).groupby("hour")[list(HEADLINE_KPIS)].mean()
g.plot(subplots=True, layout=(2,3), figsize=(13,6), title="mean KPI by hour of day"); plt.tight_layout()
"""),
    ("code", """
# KPI distributions by morphology
fig, axes = plt.subplots(1, 3, figsize=(14,4))
for ax, k in zip(axes, ["tcp_client_rtt_ms","dl_throughput_mbps","youtube_qoe_mos"]):
    for m, sub in feat.groupby("morphology"):
        sub[k].plot(kind="kde", ax=ax, label=m)
    ax.set_title(k); ax.legend()
plt.tight_layout()
"""),
    ("code", """
# serving-cell resolution quality (data-quality metric)
from networkanalysis.pipeline import resolve_serving_cells
r = resolve_serving_cells(drop_fraction=0.3)
print(f"resolved {len(r):,} tests; match rate {r.correct.mean():.1%}; "
      f"low-confidence share {(r.match_confidence<0.5).mean():.1%}")
"""),
),

"02_correlation_analysis": nb(
    ("md", "# 02 · Correlation & driver analysis\nCross-KPI, lead/lag, sibling-site, layer variance split."),
    ("code", SETUP),
    ("code", """
from networkanalysis.analytics import correlation as corr
from networkanalysis.analytics import scoring
feat = build_site_feature_table()
sc, _ = scoring.compute_scorecard(feat)
"""),
    ("code", """
# market-wide correlation matrix of the key metrics
cols = ["tcp_client_rtt_ms","tcp_server_rtt_ms","dl_throughput_mbps","vonr_mos","youtube_qoe_mos",
        "path_delay_ms","twamp_loss_pct","sevone_queue_depth","prb_util_p95","rsrq_p50"]
C = feat[cols].corr(method="spearman")
plt.figure(figsize=(8,6)); plt.imshow(C, cmap="coolwarm", vmin=-1, vmax=1)
plt.xticks(range(len(cols)), cols, rotation=90); plt.yticks(range(len(cols)), cols); plt.colorbar(); plt.title("Spearman")
"""),
    ("code", "corr.compute_correlations(feat, sc).query(\"scope=='market'\")"),
    ("code", """
# lead/lag: does SevOne queue buildup precede the YouTube QoE drop?
d = feat.groupby("ts_hour")[["sevone_queue_depth","youtube_qoe_mos"]].mean()
lags = range(-6,7)
cc = [d.sevone_queue_depth.corr(d.youtube_qoe_mos.shift(-L)) for L in lags]
plt.plot(list(lags), cc, marker="o"); plt.axvline(0, ls=":"); plt.xlabel("lag (hours)"); plt.ylabel("corr")
plt.title("queue depth vs YouTube MOS cross-correlation")
"""),
    ("code", "corr.layer_driver_split(feat, sc).describe()"),
),

"03_anomaly_detection": nb(
    ("md", "# 03 · Anomaly detection\nSTL residual + Isolation Forest / PCA + PELT changepoints, clustered into incidents."),
    ("code", SETUP),
    ("code", """
from networkanalysis.analytics import anomaly, scoring
feat = build_site_feature_table()
sc, _ = scoring.compute_scorecard(feat)
uni = anomaly.univariate_anomalies(feat, scorecard=sc)
mv  = anomaly.multivariate_anomalies(feat, sc)
print(len(uni), "univariate,", len(mv), "multivariate events")
"""),
    ("code", """
# walk one anomaly: STL decomposition of a flagged site's TCP RTT
from statsmodels.tsa.seasonal import STL
site = uni.sort_values("severity", ascending=False).iloc[0].entity_id
s = feat[feat.site_id==site].set_index("ts_hour")["tcp_client_rtt_ms"]
STL(s.interpolate(), period=24, robust=True).fit().plot(); plt.suptitle(site)
"""),
    ("code", """
det = anomaly.cluster_incidents(pd.concat([uni, mv]))
det[["start_ts","end_ts","n_sites","predicted_class","match_iou","matched_incident_id"]]
"""),
    ("code", """
# recall vs ground truth
gt = query_df("SELECT incident_id, incident_class FROM dim_incident")
print(f"{(det.match_iou>0.2).sum()} / {len(gt)} ground-truth incidents matched (IoU>0.2)")
"""),
),

"04_variability_analysis": nb(
    ("md", "# 04 · Variability analysis\nVariance components, CV / stability ranking, week-over-week drift."),
    ("code", SETUP),
    ("code", """
from networkanalysis.analytics import variability as V
feat = build_site_feature_table()
vc = V.variance_components_market(feat); vc
"""),
    ("code", """
var = V.compute_variability(feat)
var.sort_values("stability_rank").head(15)
"""),
    ("code", """
# high-variance / acceptable-mean sites - the intermittent-fault fingerprint
flag = var[var.instability_flag==1]
print(len(flag), "flagged")
site = flag.iloc[0].site_id
feat[feat.site_id==site].set_index("ts_hour")["tcp_client_rtt_ms"].plot(figsize=(12,3), title=site)
"""),
    ("code", """
# week-over-week distribution drift (PSI)
var[["site_id","wow_psi","wow_shift"]].sort_values("wow_psi", ascending=False).head(10)
"""),
),

"05_impairment_attribution": nb(
    ("md", "# 05 · Impairment attribution\nRule engine vs LightGBM vs ensemble; SHAP; accuracy vs ground truth."),
    ("code", SETUP),
    ("code", """
from networkanalysis.analytics import scoring
from networkanalysis.analytics.attribution import attribute, rule_attribution
from networkanalysis.analytics.groundtruth import load_incidents
feat = build_site_feature_table()
inc = load_incidents()
sc, _ = scoring.compute_scorecard(feat)
attr, report = attribute(feat, inc, sc)
"""),
    ("code", "import json; print(json.dumps(report['final_vs_truth_all'], indent=1))"),
    ("code", """
# confusion matrix
ev = report['final_vs_truth_all']
import numpy as np
cm = np.array(ev['confusion_matrix'])
plt.imshow(cm, cmap="Blues"); plt.xticks(range(len(ev['labels'])), ev['labels']); plt.yticks(range(len(ev['labels'])), ev['labels'])
for (i,j),v in np.ndenumerate(cm): plt.text(j,i,v,ha="center")
plt.xlabel("predicted"); plt.ylabel("true"); plt.title("final ensemble vs ground truth")
"""),
    ("code", """
# rule vs ML agreement
attr.groupby(["rule_class","ml_class"]).size().unstack(fill_value=0)
"""),
    ("code", """
# a worked example: top transport site, its evidence
row = attr[attr.final_class=="transport"].merge(sc[["site_id","impact_score"]]).sort_values("impact_score").iloc[-1]
print(row.site_id, "->", row.final_class, round(row.final_confidence,2))
print("\\n".join(json.loads(row.rule_evidence)))
print("SHAP:", row.ml_top_features)
"""),
),

"06_root_cause_walkthrough": nb(
    ("md", "# 06 · Root-cause walkthrough\nEnd-to-end on 2-3 detected incidents: attribution + anomaly cluster + topology localisation."),
    ("code", SETUP),
    ("code", """
rca = query_df("SELECT * FROM rca_finding WHERE scope='incident'")
det = query_df("SELECT * FROM incident_detected")
rca
"""),
    ("code", """
import json
for _, r in rca.iterrows():
    print("="*70)
    print(r.candidate_cause, "  conf", round(r.confidence,2), " matched:", r.matched_incident_id)
    print("entity:", r.candidate_entity)
    for e in json.loads(r.evidence): print("  -", e)
    print("ACTION:", r.recommended_action)
"""),
    ("code", """
# show the affected-site cluster for the first localised transport incident on the map
d = det[det.predicted_class=='transport'].iloc[0]
sites = json.loads(d.site_ids)
ll = query_df("SELECT site_id, lat, lon FROM dim_site")
plt.figure(figsize=(6,6))
plt.scatter(ll.lon, ll.lat, s=4, c="#ccc")
sub = ll[ll.site_id.isin(sites)]
plt.scatter(sub.lon, sub.lat, s=40, c="#e8663c")
plt.title(f"detected transport incident: {len(sites)} sites")
"""),
),

"07_report_generation": nb(
    ("md", "# 07 · Report generation\nParameterised entry point for the analytics report (Papermill target)."),
    ("code", "PRESET = 'mixed_realistic'  # papermill parameter"),
    ("code", """
from networkanalysis.report import build_report
out = build_report(fmt="html")
out
"""),
    ("code", """
from IPython.display import IFrame
IFrame(src="../reports/analytics_report.html", width="100%", height=600)
"""),
),
}


def main() -> None:
    for name, content in NOTEBOOKS.items():
        (HERE / f"{name}.ipynb").write_text(json.dumps(content, indent=1), encoding="utf-8")
        print("wrote", name + ".ipynb")


if __name__ == "__main__":
    main()
