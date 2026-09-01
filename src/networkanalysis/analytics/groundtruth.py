"""Turn ``dim_incident`` rows into per-site and per-(site,hour) ground-truth labels.

Used both to *train* the attribution classifier and to *score* every module against truth.
"""

from __future__ import annotations

import json

import pandas as pd

from networkanalysis.db.database import connect

CLASS_ORDER = ["none", "transport", "ran", "shared"]


def load_incidents(db_path=None) -> pd.DataFrame:
    con = connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM dim_incident", con)
    finally:
        con.close()
    if df.empty:
        return df
    df["start_ts"] = pd.to_datetime(df["start_ts"])
    df["end_ts"] = pd.to_datetime(df["end_ts"])
    df["sites"] = df["affected_site_ids"].apply(lambda s: json.loads(s or "[]"))
    df["links"] = df["affected_link_ids"].apply(lambda s: json.loads(s or "[]"))
    return df


def site_hour_labels(feat: pd.DataFrame, incidents: pd.DataFrame) -> pd.Series:
    """Label each (site_id, ts_hour) row of the feature table with the active incident class."""
    label = pd.Series("none", index=feat.index, dtype=object)
    weight = pd.Series(0.0, index=feat.index)
    if incidents.empty:
        return label
    fi = feat[["site_id", "ts_hour"]].copy()
    fi["ts_hour"] = pd.to_datetime(fi["ts_hour"])
    for _, inc in incidents.iterrows():
        if not inc["sites"]:
            continue
        m = (
            fi.site_id.isin(inc["sites"])
            & (fi.ts_hour >= inc.start_ts.floor("h"))
            & (fi.ts_hour <= inc.end_ts.ceil("h"))
        )
        better = m & (inc.magnitude > weight)
        label.loc[better] = inc.incident_class
        weight.loc[better] = inc.magnitude
    return label


def site_truth(feat: pd.DataFrame, incidents: pd.DataFrame, worst_windows: pd.DataFrame) -> pd.DataFrame:
    """Per-site true class = class of the incident with the largest magnitude*overlap in
    the site's worst window (else 'none')."""
    rows = []
    ww = worst_windows.set_index("site_id")
    for site in feat.site_id.unique():
        tc, tconf, tid = "none", 0.0, None
        if not incidents.empty and site in ww.index:
            w0 = pd.Timestamp(ww.loc[site, "worst_window_start"])
            w1 = pd.Timestamp(ww.loc[site, "worst_window_end"])
            for _, inc in incidents.iterrows():
                if site not in inc["sites"]:
                    continue
                ov = (min(w1, inc.end_ts) - max(w0, inc.start_ts)).total_seconds()
                if ov <= 0:
                    continue
                score = inc.magnitude * min(ov / 3600.0, 12)
                if score > tconf:
                    tc, tconf, tid = inc.incident_class, score, inc.incident_id
        rows.append({"site_id": site, "true_class": tc, "true_incident_id": tid})
    return pd.DataFrame(rows)


def classification_report(y_true: pd.Series, y_pred: pd.Series) -> dict:
    from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

    labels = [c for c in CLASS_ORDER if c in set(y_true) | set(y_pred)]
    cm = confusion_matrix(y_true, y_pred, labels=labels).tolist()
    out = {
        "labels": labels,
        "confusion_matrix": cm,
        "accuracy": float((y_true.to_numpy() == y_pred.to_numpy()).mean()),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
    }
    for cls in labels:
        out[cls] = {
            "precision": float(precision_score(y_true == cls, y_pred == cls, zero_division=0)),
            "recall": float(recall_score(y_true == cls, y_pred == cls, zero_division=0)),
            "f1": float(f1_score(y_true == cls, y_pred == cls, zero_division=0)),
            "support": int((y_true == cls).sum()),
        }
    return out
