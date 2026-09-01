"""Transport-vs-RAN impairment attribution.

Three stages, all reported so a technician can see the reasoning:
  1. deterministic **rule engine** - RSRP/RSRQ/PRB signatures vs TWAMP/SevOne/TCP-split
     signatures + a shared-path sibling-degradation check;
  2. a **LightGBM classifier** trained on the ``dim_incident`` ground truth, with SHAP
     feature attributions;
  3. a calibrated **ensemble** of the two.
Evaluation vs ground truth (precision/recall/F1, confusion matrix) is returned by
:func:`attribute`.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from networkanalysis.analytics.groundtruth import (
    classification_report,
    site_hour_labels,
    site_truth,
)
from networkanalysis.db.database import connect

RADIO_FEATURES = ["rsrp_p50__z", "rsrq_p50__z", "prb_util_p95__z", "rsrp_p50__peer_z", "rsrq_p50__peer_z"]
TRANSPORT_FEATURES = [
    "path_delay_ms__z", "path_jitter_ms__z", "path_loss_pct__z",
    "twamp_rtt_ms__z", "twamp_jitter_ms__z", "twamp_loss_pct__z",
    "sevone_util_pct__z", "sevone_queue_depth__z", "sevone_discards__z", "sevone_crc__z",
    "tcp_client_rtt_ms__z", "tcp_server_rtt_ms__z", "retrans_pct__z",
]
SESSION_FEATURES = ["tcp_fail_pct__z", "dl_throughput_mbps__z", "vonr_mos__z", "youtube_qoe_mos__z",
                    "loaded_latency_ms__z"]
ALL_FEATURES = RADIO_FEATURES + TRANSPORT_FEATURES + SESSION_FEATURES


# --------------------------------------------------------------------------- rules
def _window_slice(feat: pd.DataFrame, worst: pd.DataFrame) -> pd.DataFrame:
    w = worst.set_index("site_id")
    f = feat.copy()
    f["_ws"] = pd.to_datetime(f.site_id.map(w["worst_window_start"]))
    f["_we"] = pd.to_datetime(f.site_id.map(w["worst_window_end"]))
    m = (f.ts_hour >= f._ws) & (f.ts_hour <= f._we)
    return f[m].drop(columns=["_ws", "_we"])


def _sibling_degradation(feat_win: pd.DataFrame, db_path) -> pd.Series:
    """For each site, fraction of *other* sites sharing its pre-agg uplink that are also
    transport-degraded in the same window."""
    con = connect(db_path)
    try:
        pl = pd.read_sql_query(
            "SELECT p.site_id, p.link_id FROM dim_path_link p "
            "JOIN dim_link l ON l.link_id = p.link_id WHERE l.kind='preagg_uplink'", con
        )
    finally:
        con.close()
    site_tr = (
        feat_win.assign(tr=lambda d: (d[TRANSPORT_FEATURES].clip(lower=0).mean(axis=1) > 1.2).astype(int))
        .groupby("site_id")["tr"].max()
    )
    pl = pl.merge(site_tr.rename("tr"), on="site_id", how="left").fillna({"tr": 0})
    link_stats = pl.groupby("link_id")["tr"].agg(["sum", "count"])
    out = {}
    for _, r in pl.iterrows():
        s, c = link_stats.loc[r.link_id]
        out[r.site_id] = float((s - r.tr) / max(c - 1, 1))
    return pd.Series(out)


def _worst_agg(fw: pd.DataFrame, col: str, how: str) -> pd.Series:
    """max of (own z, 0.7 * peer z) per site in the worst window, then reduce."""
    own = fw.get(f"{col}__z")
    peer = fw.get(f"{col}__peer_z")
    if own is None:
        return pd.Series(0.0, index=fw.site_id.unique())
    combined = own.fillna(0)
    if peer is not None:
        combined = np.maximum(combined, 0.7 * peer.fillna(0))
    tmp = pd.DataFrame({"site_id": fw.site_id, "v": combined})
    return tmp.groupby("site_id")["v"].agg(how)


def rule_attribution(feat: pd.DataFrame, worst: pd.DataFrame, db_path=None) -> pd.DataFrame:
    fw = _window_slice(feat, worst)
    if fw.empty:
        fw = feat
    A = pd.DataFrame(index=sorted(fw.site_id.unique()))
    A["rsrp"] = _worst_agg(fw, "rsrp_p50", "min")
    A["rsrq"] = _worst_agg(fw, "rsrq_p50", "min")
    A["prb"] = _worst_agg(fw, "prb_util_p95", "max")
    A["path_loss"] = _worst_agg(fw, "path_loss_pct", "max")
    A["path_delay"] = _worst_agg(fw, "path_delay_ms", "max")
    A["twamp_loss"] = _worst_agg(fw, "twamp_loss_pct", "max")
    A["twamp_jit"] = _worst_agg(fw, "twamp_jitter_ms", "max")
    A["sev_queue"] = _worst_agg(fw, "sevone_queue_depth", "max")
    A["sev_crc"] = _worst_agg(fw, "sevone_crc", "max")
    A["sev_util"] = _worst_agg(fw, "sevone_util_pct", "max")
    A["client_rtt"] = _worst_agg(fw, "tcp_client_rtt_ms", "max")
    A["server_rtt"] = _worst_agg(fw, "tcp_server_rtt_ms", "max")
    A["retrans"] = _worst_agg(fw, "retrans_pct", "max")
    A["tcp_fail"] = _worst_agg(fw, "tcp_fail_pct", "max")
    # headline badness: how degraded is the user experience at all
    head = fw.assign(_b=np.maximum.reduce([
        np.clip(fw.get("tcp_client_rtt_ms__z", 0).fillna(0), 0, None),
        np.clip(fw.get("tcp_fail_pct__z", 0).fillna(0), 0, None),
        np.clip(-fw.get("dl_throughput_mbps__z", 0).fillna(0), 0, None),
        np.clip(-fw.get("vonr_mos__z", 0).fillna(0), 0, None),
        np.clip(-fw.get("youtube_qoe_mos__z", 0).fillna(0), 0, None),
    ]))
    A["headline_bad"] = head.groupby("site_id")["_b"].max()
    A["avail"] = _worst_agg(fw, "availability", "min")
    sib = _sibling_degradation(fw, db_path).reindex(A.index).fillna(0.0)

    rows = []
    for site, r in A.iterrows():
        radio_sig = max(-r.rsrq, -r.rsrp, r.prb / 1.4)
        # PURE transport signals come from the transport layer's own instrumentation
        # (TWAMP active probes, SevOne device counters, per-link delay/loss). TCP
        # client-RTT and retransmissions are AMBIGUOUS - radio scheduling delay and
        # BLER drive them too - so they only count once a pure signal is present.
        pure_transport = max(
            r.path_loss, r.path_delay, r.twamp_loss, r.twamp_jit,
            r.sev_queue, r.sev_crc, r.sev_util / 1.6,
        )
        client_server_split = r.client_rtt - max(r.server_rtt, 0)
        transport_sig = pure_transport
        if pure_transport > 1.0:                       # corroborate with session-side & siblings
            transport_sig += 0.4 * max(client_server_split, 0) + 0.35 * max(r.retrans, 0) + 1.3 * sib[site]
        elif sib[site] > 0.35:                          # sibling cluster alone is weak evidence
            transport_sig += 0.8 * sib[site]
        avail_sig = -r.avail

        ev = []
        if -r.rsrp > 2.0:
            ev.append(f"RSRP {r.rsrp:+.1f}sigma below baseline")
        if -r.rsrq > 1.8:
            ev.append(f"RSRQ {r.rsrq:+.1f}sigma below baseline")
        if r.prb > 2.5:
            ev.append(f"PRB utilisation {r.prb:+.1f}sigma (near exhaustion)")
        if r.twamp_loss > 1.8:
            ev.append(f"TWAMP frame loss {r.twamp_loss:+.1f}sigma")
        if r.sev_queue > 1.8:
            ev.append(f"SevOne queue depth {r.sev_queue:+.1f}sigma")
        if r.sev_crc > 1.8:
            ev.append(f"SevOne CRC errors {r.sev_crc:+.1f}sigma")
        if r.path_loss > 1.8 or r.path_delay > 1.8:
            ev.append(f"transport path delay/loss elevated ({max(r.path_loss, r.path_delay):+.1f}sigma)")
        if (r.client_rtt - max(r.server_rtt, 0)) > 1.5:
            ev.append(f"TCP client-RTT up {r.client_rtt:+.1f}sigma while server-RTT flat")
        if r.retrans > 1.8:
            ev.append(f"TCP retransmissions {r.retrans:+.1f}sigma")
        if sib[site] > 0.25:
            ev.append(f"{sib[site]*100:.0f}% of sibling sites on the shared uplink also transport-degraded")

        if r.headline_bad < 1.5 and avail_sig < 3:
            cls, conf = "none", round(float(np.clip(0.3 + 0.1 * r.headline_bad, 0.3, 0.5)), 3)
            ev.append("no material user-experience degradation in the worst window")
        elif avail_sig > 3.5 and max(radio_sig, pure_transport) < 2.0:
            cls, conf = "shared", 0.58
            ev.append("availability collapse with no isolated radio or transport signature")
        elif radio_sig > 2.0 and pure_transport < 1.5:
            # clear radio signature, no transport-layer corroboration -> RAN
            cls = "ran"
            conf = float(np.clip(0.55 + 0.1 * radio_sig, 0.55, 0.95))
            ev.append("radio KPI degraded with no TWAMP/SevOne/path corroboration -> RAN-attributed")
        else:
            cands = {"transport": transport_sig, "ran": radio_sig}
            cls = max(cands, key=cands.get)
            lead = cands[cls]
            other = min(cands.values())
            margin = lead - other
            if lead < 1.3:
                cls = "shared" if avail_sig > 1.5 else cls
                conf = 0.42
                ev.append("degraded experience with only weak infrastructure signatures")
            else:
                conf = float(np.clip(0.5 + 0.09 * lead + 0.12 * margin, 0.5, 0.97))
                if margin < 0.8:
                    conf = min(conf, 0.6)
                    ev.append("mixed radio + transport signature - reduced confidence")
        rows.append({
            "site_id": site, "rule_class": cls, "rule_confidence": round(float(conf), 3),
            "rule_evidence": json.dumps(ev), "sibling_degraded_frac": round(float(sib[site]), 3),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- ML
def _site_hour_features(feat: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ALL_FEATURES if c in feat.columns]
    X = feat[["site_id", "ts_hour", *cols]].copy()
    X[cols] = X[cols].fillna(0.0).clip(-25, 25)
    return X


def ml_attribution(feat: pd.DataFrame, incidents: pd.DataFrame, worst: pd.DataFrame):
    from lightgbm import LGBMClassifier
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import train_test_split

    X = _site_hour_features(feat)
    cols = [c for c in ALL_FEATURES if c in X.columns]
    y = site_hour_labels(feat, incidents).values

    result = {"available": False}
    if len(set(y)) < 2 or (pd.Series(y) != "none").sum() < 50:
        # not enough labelled signal - skip ML, rules carry it
        preds = pd.DataFrame({"site_id": feat.site_id.unique()})
        preds["ml_class"] = "none"
        preds["ml_confidence"] = 0.0
        preds["ml_top_features"] = "[]"
        return preds, result

    def _mk():
        return LGBMClassifier(
            n_estimators=220, learning_rate=0.06, num_leaves=31, subsample=0.8,
            colsample_bytree=0.8, class_weight="balanced", verbose=-1, n_jobs=-1,
        )

    Xtr, Xte, ytr, yte = train_test_split(X[cols], y, test_size=0.25, random_state=0, stratify=y)
    clf = _mk().fit(Xtr, ytr)
    hold_pred = clf.predict(Xte)
    result.update(
        available=True,
        holdout=classification_report(pd.Series(yte), pd.Series(hold_pred)),
        n_train=int(len(ytr)),
    )

    # refit on all data (calibrated) for deployment predictions
    clf_full = CalibratedClassifierCV(_mk(), method="isotonic", cv=3).fit(X[cols], y)
    proba = clf_full.predict_proba(X[cols])
    classes = list(clf_full.classes_)
    ph = pd.DataFrame(proba, columns=classes)
    ph["site_id"] = X.site_id.values
    ph["ts_hour"] = X.ts_hour.values

    # SHAP on the underlying booster (fit a plain model for explanation)
    top_features_by_site: dict[str, list] = {}
    try:
        import shap

        expl_model = LGBMClassifier(n_estimators=180, learning_rate=0.07, num_leaves=31,
                                    class_weight="balanced", verbose=-1, n_jobs=-1).fit(X[cols], y)
        w = _window_slice(X.assign(**{}), worst)
        w = w if not w.empty else X
        if len(w) > 8000:
            w = w.sample(8000, random_state=0)
        sv = shap.TreeExplainer(expl_model).shap_values(w[cols])
        classes_e = list(expl_model.classes_)
        tr_i = classes_e.index("transport") if "transport" in classes_e else 0
        if isinstance(sv, list):                    # older shap: list per class
            sv_tr = sv[tr_i]
        else:
            sv_arr = np.asarray(sv)
            sv_tr = sv_arr[:, :, tr_i] if sv_arr.ndim == 3 else sv_arr
        contrib = pd.DataFrame(np.abs(sv_tr), columns=cols)
        contrib["site_id"] = w.site_id.values
        for site, g in contrib.groupby("site_id"):
            top = g[cols].mean().sort_values(ascending=False).head(4)
            top_features_by_site[site] = [[k.replace("__z", ""), round(float(v), 3)] for k, v in top.items()]
    except Exception as e:  # pragma: no cover
        result["shap_error"] = str(e)

    # aggregate site-hour probs over the worst window -> per-site prediction
    ww = worst.set_index("site_id")
    ph["_ws"] = pd.to_datetime(ph.site_id.map(ww["worst_window_start"]))
    ph["_we"] = pd.to_datetime(ph.site_id.map(ww["worst_window_end"]))
    inwin = (ph.ts_hour >= ph._ws) & (ph.ts_hour <= ph._we)
    src = ph[inwin] if inwin.any() else ph
    site_proba = src.groupby("site_id")[classes].mean()
    ml_class = site_proba.idxmax(axis=1)
    ml_conf = site_proba.max(axis=1)
    preds = pd.DataFrame({
        "site_id": site_proba.index,
        "ml_class": ml_class.values,
        "ml_confidence": ml_conf.round(3).values,
        "ml_top_features": [json.dumps(top_features_by_site.get(s, [])) for s in site_proba.index],
    })
    return preds, result


# --------------------------------------------------------------------------- ensemble
def attribute(feat: pd.DataFrame, incidents: pd.DataFrame, scorecard: pd.DataFrame,
              db_path=None) -> tuple[pd.DataFrame, dict]:
    worst = scorecard[["site_id", "worst_window_start", "worst_window_end"]].copy()
    rules = rule_attribution(feat, worst, db_path)
    ml, ml_info = ml_attribution(feat, incidents, worst)

    m = rules.merge(ml, on="site_id", how="outer")
    m["rule_class"] = m["rule_class"].fillna("none")
    m["ml_class"] = m["ml_class"].fillna("none")
    m["rule_confidence"] = m["rule_confidence"].fillna(0.4)
    m["ml_confidence"] = m["ml_confidence"].fillna(0.0)

    final_cls, final_conf = [], []
    for _, r in m.iterrows():
        if not ml_info.get("available"):
            final_cls.append(r.rule_class)
            final_conf.append(r.rule_confidence)
            continue
        if r.rule_class == r.ml_class:
            final_cls.append(r.rule_class)
            final_conf.append(float(np.clip(0.55 + 0.45 * (r.rule_confidence + r.ml_confidence) / 2, 0, 0.99)))
        elif r.rule_class == "ran" and r.rule_confidence >= 0.6:
            # the rule engine's clean-radio-signature path is a strong guardrail: a
            # confident RAN call outranks an ML "transport" vote (the ML tends to
            # over-predict transport because those hours dominate training).
            final_cls.append("ran")
            final_conf.append(float(r.rule_confidence * 0.9))
        elif r.ml_confidence >= r.rule_confidence:
            final_cls.append(r.ml_class)
            final_conf.append(float(r.ml_confidence * 0.8))
        else:
            final_cls.append(r.rule_class)
            final_conf.append(float(r.rule_confidence * 0.8))
    m["final_class"] = final_cls
    m["final_confidence"] = np.round(final_conf, 3)

    # ---- evaluation vs ground truth ----
    truth = site_truth(feat, incidents, scorecard[["site_id", "worst_window_start", "worst_window_end"]])
    m = m.merge(truth, on="site_id", how="left")
    m["matched_incident_id"] = m["true_incident_id"]
    m["matched_incident_class"] = m["true_class"]

    flagged = scorecard[scorecard.is_priority == 1].site_id
    evalset = m[m.site_id.isin(flagged)]
    report = {
        "ml": ml_info,
        "rule_vs_truth_all": classification_report(m.true_class.fillna("none"), m.rule_class),
        "final_vs_truth_all": classification_report(m.true_class.fillna("none"), m.final_class),
        "final_vs_truth_priority": classification_report(
            evalset.true_class.fillna("none"), evalset.final_class
        ) if len(evalset) else {},
    }
    out_cols = [
        "site_id", "rule_class", "rule_confidence", "rule_evidence",
        "ml_class", "ml_confidence", "ml_top_features",
        "final_class", "final_confidence", "matched_incident_id", "matched_incident_class",
    ]
    return m[out_cols], report
