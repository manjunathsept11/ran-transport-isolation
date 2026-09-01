import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useSite } from "../api";
import { Card, Spinner, ErrorBox, Tag, Stat } from "../ui";
import { TimeSeries } from "../charts";
import { C, fmt } from "../theme";

export default function SiteDetail() {
  const { id = "" } = useParams();
  const { data, isLoading, error } = useSite(id);
  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  const { site, scorecard: sc, attribution: attr, hourly, anomalies, rca, path, variability: v, ground_truth_incidents: gt, correlations } = data;
  const marks = anomalies.map((a: any) => ({ xAxis: a.peak_ts, color: C.bad }));

  return (
    <div className="space-y-5">
      <Link to="/priority" className="text-muted text-sm flex items-center gap-1 hover:text-ink">
        <ArrowLeft size={14} /> Priority sites
      </Link>
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-3">
            {site.site_id}
            {attr && <Tag kind={attr.final_class} />}
          </h1>
          <p className="text-muted text-sm">
            {site.region} · {site.morphology} · {site.backhaul_type} backhaul
            {sc && ` · rank #${sc.rank} · impact ${fmt(sc.impact_score, 1)}`}
          </p>
        </div>
        {attr && (
          <div className="text-right text-sm">
            <div className="text-muted">attribution confidence</div>
            <div className="text-2xl font-semibold">{fmt(attr.final_confidence, 2)}</div>
            <div className="text-xs text-muted">rule {attr.rule_class} · ML {attr.ml_class}</div>
          </div>
        )}
      </div>

      {/* attribution reasoning */}
      {attr && (
        <Card title="Why this attribution">
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-muted uppercase mb-1">Rule evidence</div>
              <ul className="text-sm space-y-1 list-disc pl-4">
                {(attr.rule_evidence || []).map((e: string, i: number) => <li key={i}>{e}</li>)}
              </ul>
            </div>
            <div>
              <div className="text-xs text-muted uppercase mb-1">Top model features (SHAP)</div>
              <div className="space-y-1">
                {(attr.ml_top_features || []).map(([k, val]: [string, number], i: number) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="w-40 text-muted truncate">{k}</span>
                    <div className="flex-1 h-1.5 bg-line rounded-full overflow-hidden">
                      <div className="h-full bg-accent" style={{ width: `${Math.min(100, val * 400)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* radio vs transport panels */}
      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Radio">
          <TimeSeries height={200} data={hourly} markLines={marks}
            series={[
              { key: "rsrp_p50", name: "RSRP (dBm)", color: C.ran },
              { key: "rsrq_p50", name: "RSRQ (dB)", color: C.shared, yAxis: 1 },
              { key: "prb_util_p95", name: "PRB util %", color: C.warn, yAxis: 1 },
            ]} />
        </Card>
        <Card title="Transport path">
          <TimeSeries height={200} data={hourly} markLines={marks}
            series={[
              { key: "path_delay_ms", name: "path delay (ms)", color: C.transport },
              { key: "twamp_loss_pct", name: "TWAMP loss %", color: C.bad, yAxis: 1 },
              { key: "sevone_queue_depth", name: "SevOne queue", color: C.warn, yAxis: 1 },
            ]} />
        </Card>
      </div>

      <Card title="End-user experience">
        <TimeSeries height={220} data={hourly} markLines={marks}
          series={[
            { key: "tcp_client_rtt_ms", name: "TCP client RTT", color: C.transport },
            { key: "tcp_server_rtt_ms", name: "TCP server RTT (control)", color: C.muted },
            { key: "dl_throughput_mbps", name: "DL Mbps", color: C.good, yAxis: 1 },
            { key: "youtube_qoe_mos", name: "YouTube MOS", color: C.ran, yAxis: 1 },
          ]} />
      </Card>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Transport path topology">
          <div className="flex items-center gap-2 flex-wrap text-sm">
            <span className="px-2 py-1 rounded bg-panel2 border border-line">{site.site_id}</span>
            {path.map((h: any) => (
              <span key={h.hop_index} className="flex items-center gap-2">
                <span className="text-muted">──{h.media}──▶</span>
                <span className="px-2 py-1 rounded bg-panel2 border border-line" title={h.link_id}>
                  {h.endpoint_b} <span className="text-muted text-xs">({h.kind}, {fmt(h.capacity_mbps, 0)}M)</span>
                </span>
              </span>
            ))}
          </div>
          {rca.length > 0 && (
            <div className="mt-4 border-t border-line pt-3 space-y-2">
              {rca.map((r: any, i: number) => (
                <div key={i} className="text-sm">
                  <div className="font-medium">{r.candidate_cause} <span className="text-muted">({fmt(r.confidence, 2)})</span></div>
                  <div className="text-muted">{r.recommended_action}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Anomalies & variability">
          <div className="grid grid-cols-2 gap-3 mb-3">
            <Stat label="Anomaly events" value={anomalies.length} />
            <Stat label="Stability rank" value={v?.stability_rank ?? "-"}
                  tone={v?.instability_flag ? "warn" : undefined}
                  sub={v?.instability_flag ? "high-variance-low-mean" : "stable"} />
          </div>
          <table className="w-full text-xs">
            <tbody>
              {anomalies.slice(0, 6).map((a: any, i: number) => (
                <tr key={i} className="border-t border-line/60">
                  <td className="py-1">{a.metric}</td>
                  <td className="text-muted">{String(a.start_ts).slice(5, 16)}</td>
                  <td className="text-right">σ {fmt(a.severity, 1)}</td>
                  <td className="text-right text-muted">{a.method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      {gt.length > 0 && (
        <Card title="Ground truth (demo mode)">
          <div className="flex gap-2 flex-wrap">
            {gt.map((g: any) => (
              <div key={g.incident_id} className="text-xs px-2 py-1 rounded bg-panel2 border border-line">
                <Tag kind={g.class} /> {g.kind} · {String(g.start_ts).slice(5, 16)} → {String(g.end_ts).slice(5, 16)} · mag {fmt(g.magnitude, 2)}
              </div>
            ))}
          </div>
        </Card>
      )}

      {correlations?.length > 0 && (
        <Card title="Correlated KPI pairs at this site">
          <table className="w-full text-sm">
            <thead><tr className="text-muted text-xs"><th className="text-left py-1">A</th><th className="text-left">B</th><th>Spearman</th><th>Partial</th><th>Best lag</th></tr></thead>
            <tbody>
              {correlations.slice(0, 8).map((c: any, i: number) => (
                <tr key={i} className="border-t border-line/60">
                  <td className="py-1">{c.metric_a}</td><td>{c.metric_b}</td>
                  <td className="text-center">{fmt(c.spearman, 2)}</td>
                  <td className="text-center">{fmt(c.partial, 2)}</td>
                  <td className="text-center text-muted">{c.best_lag_min}m</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
