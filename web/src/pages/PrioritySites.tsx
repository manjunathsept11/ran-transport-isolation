import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { useScorecard } from "../api";
import { Card, DataTable, Spinner, ErrorBox, Tag, Bar } from "../ui";
import { C, fmt, fmtInt } from "../theme";

export default function PrioritySites() {
  const { data, isLoading, error } = useScorecard(true);
  const nav = useNavigate();
  const [attr, setAttr] = useState("all");
  const [region, setRegion] = useState("all");

  const regions = useMemo(
    () => Array.from(new Set((data || []).map((d) => d.region))).sort(),
    [data],
  );
  const rows = useMemo(
    () =>
      (data || []).filter(
        (d) =>
          (attr === "all" || d.primary_attribution === attr) &&
          (region === "all" || d.region === region),
      ),
    [data, attr, region],
  );

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold">Priority Sites</h1>
          <p className="text-muted text-sm">{rows.length} of {data?.length} shown — ranked for Phase-2 field audit</p>
        </div>
        <div className="flex items-center gap-2">
          <select className="inp w-auto" value={attr} onChange={(e) => setAttr(e.target.value)}>
            <option value="all">all causes</option>
            <option value="transport">transport</option>
            <option value="ran">RAN</option>
            <option value="shared">shared</option>
            <option value="none">unclear</option>
          </select>
          <select className="inp w-auto" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="all">all regions</option>
            {regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <a className="btn" href="/api/report/audit.xlsx">
            <Download size={15} /> Audit list (xlsx)
          </a>
        </div>
      </div>

      <Card>
        <DataTable
          rows={rows}
          initialSort={{ key: "rank", dir: "asc" }}
          onRowClick={(r) => nav(`/sites/${r.site_id}`)}
          columns={[
            { key: "rank", header: "#", width: 44, sortVal: (r) => r.rank },
            { key: "site_id", header: "Site", render: (r) => <b>{r.site_id}</b> },
            { key: "region", header: "Region" },
            { key: "morphology", header: "Morph" },
            {
              key: "impact_score", header: "Impact", sortVal: (r) => r.impact_score,
              render: (r) => (
                <div className="flex items-center gap-2 w-32">
                  <span className="tabular-nums w-10">{fmt(r.impact_score, 1)}</span>
                  <Bar value={r.impact_score} max={data![0].impact_score} />
                </div>
              ),
            },
            {
              key: "primary_attribution", header: "Cause",
              render: (r) => <Tag kind={r.primary_attribution} />,
            },
            {
              key: "attribution_confidence", header: "Conf.", sortVal: (r) => r.attribution_confidence,
              render: (r) => <span className="tabular-nums">{fmt(r.attribution_confidence, 2)}</span>,
            },
            {
              key: "kpis", header: "Headline severity",
              render: (r) => (
                <div className="flex gap-1">
                  {[
                    ["RTT", r.severity_tcp_rtt],
                    ["Fail", r.severity_tcp_fail],
                    ["Thr", r.severity_throughput],
                    ["VoNR", r.severity_vonr],
                    ["YT", r.severity_youtube],
                  ].map(([k, v]) => (
                    <span key={k as string}
                      title={`${k}: ${fmt(v as number, 2)}`}
                      className="w-6 h-6 grid place-items-center rounded text-[9px] font-semibold"
                      style={{
                        background: `rgba(240,118,60,${Math.min(1, (v as number) / 1.2) * 0.9})`,
                        color: (v as number) > 0.5 ? "#fff" : C.muted,
                      }}>
                      {k}
                    </span>
                  ))}
                </div>
              ),
            },
            {
              key: "sessions_impacted", header: "Sessions", sortVal: (r) => r.sessions_impacted,
              render: (r) => <span className="tabular-nums">{fmtInt(r.sessions_impacted)}</span>,
            },
            {
              key: "worst_window_start", header: "Worst window",
              render: (r) => <span className="text-muted text-xs">{String(r.worst_window_start).slice(5, 16)}</span>,
            },
          ]}
        />
      </Card>
    </div>
  );
}
