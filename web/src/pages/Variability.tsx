import { useNavigate } from "react-router-dom";
import { useStatus, useVariability } from "../api";
import { Card, DataTable, Spinner, ErrorBox, Tag, Stat } from "../ui";
import { BarChart } from "../charts";
import { C, fmt } from "../theme";

export default function Variability() {
  const { data, isLoading, error } = useVariability();
  const { data: status } = useStatus();
  const nav = useNavigate();
  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  const vc = status?.analytics?.metrics?.variability?.variance_components || {};
  const flagged = data.sites.filter((s: any) => s.instability_flag);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Variability Analysis</h1>
        <p className="text-muted text-sm">
          TCP client-RTT stability · {flagged.length} sites flagged high-variance / acceptable-mean
          (intermittent-fault fingerprint)
        </p>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card title="Variance decomposition (TCP client RTT)">
          <BarChart height={200} horizontal
            items={Object.entries(vc).map(([k, v]) => ({ name: k, value: Number(v), color: C.grid[0] }))} />
          <p className="text-xs text-muted mt-2">
            Share of total variance attributable to each factor.
          </p>
        </Card>
        <Card title="Week-over-week drift">
          <Stat label="Sites with PSI &gt; 0.2" value={data.sites.filter((s: any) => s.wow_shift).length} />
          <p className="text-xs text-muted mt-2">
            Population Stability Index between the first and second half of the run.
          </p>
        </Card>
        <Card title="Layer driver split (median)">
          {data.drivers.length ? (
            <>
              <BarChart height={150} horizontal items={[
                { name: "transport", value: median(data.drivers.map((d: any) => d.transport_share)), color: C.transport },
                { name: "radio", value: median(data.drivers.map((d: any) => d.radio_share)), color: C.ran },
              ]} />
              <p className="text-xs text-muted mt-2">
                Share of YouTube-QoE variance explained by each layer, across priority sites.
              </p>
            </>
          ) : <div className="text-muted text-sm">n/a</div>}
        </Card>
      </div>

      <Card title="Least stable sites">
        <DataTable
          rows={data.sites.slice(0, 60)}
          initialSort={{ key: "stability_rank", dir: "asc" }}
          onRowClick={(r: any) => nav(`/sites/${r.site_id}`)}
          columns={[
            { key: "stability_rank", header: "#", width: 44 },
            { key: "site_id", header: "Site", render: (r: any) => <b>{r.site_id}</b> },
            { key: "region", header: "Region" },
            { key: "primary_attribution", header: "Cause", render: (r: any) => <Tag kind={r.primary_attribution || "none"} /> },
            { key: "cv", header: "CV", sortVal: (r: any) => r.cv || 0, render: (r: any) => fmt(r.cv, 3) },
            { key: "busy_offpeak_ratio", header: "Busy/off-peak", render: (r: any) => fmt(r.busy_offpeak_ratio, 2) },
            { key: "day_to_day_var", header: "Day-to-day var", render: (r: any) => fmt(r.day_to_day_var, 1) },
            { key: "wow_shift", header: "WoW drift", render: (r: any) => (r.wow_shift ? <span className="text-warn">yes</span> : "no") },
            { key: "instability_flag", header: "", render: (r: any) => (r.instability_flag ? <Tag kind="shared" /> : null) },
          ]}
        />
      </Card>
    </div>
  );
}

function median(a: number[]) {
  const s = [...a].filter((x) => x != null).sort((x, y) => x - y);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
}
