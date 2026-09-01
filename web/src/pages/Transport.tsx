import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLink, useLinks } from "../api";
import { Card, DataTable, Spinner, ErrorBox, Tag, Bar } from "../ui";
import { TimeSeries } from "../charts";
import { C, fmt } from "../theme";

export default function Transport() {
  const { data: links, isLoading, error } = useLinks();
  const [sel, setSel] = useState<string>("");
  const { data: detail } = useLink(sel);
  const nav = useNavigate();

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;

  const shared = (links || []).filter((l) => l.kind !== "access");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Transport Paths &amp; Links</h1>
        <p className="text-muted text-sm">Shared uplinks ranked by worst observed loss — click to inspect sibling sites</p>
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title={`Shared transport links (${shared.length})`}>
          <DataTable
            rows={shared}
            initialSort={{ key: "loss_pct", dir: "desc" }}
            onRowClick={(r) => setSel(r.link_id)}
            dense
            columns={[
              { key: "link_id", header: "Link", render: (r) => <span className="text-xs">{r.link_id}</span> },
              { key: "kind", header: "Kind", render: (r) => <span className="text-xs text-muted">{r.kind}</span> },
              { key: "media", header: "Media" },
              { key: "site_count", header: "Sites", sortVal: (r) => r.site_count },
              {
                key: "util_pct", header: "Util%", sortVal: (r) => r.util_pct || 0,
                render: (r) => (
                  <div className="w-24 flex items-center gap-1">
                    <span className="w-8 tabular-nums text-xs">{fmt(r.util_pct, 0)}</span>
                    <Bar value={r.util_pct || 0} max={100} color={r.util_pct > 85 ? C.bad : C.accent} />
                  </div>
                ),
              },
              {
                key: "loss_pct", header: "Loss%", sortVal: (r) => r.loss_pct || 0,
                render: (r) => <span className={r.loss_pct > 1 ? "text-bad" : ""}>{fmt(r.loss_pct, 2)}</span>,
              },
            ]}
          />
        </Card>

        <Card title={detail ? `Link ${detail.link.link_id}` : "Select a link"}>
          {!detail ? (
            <div className="text-muted text-sm p-6 text-center">pick a link on the left</div>
          ) : (
            <>
              <div className="text-sm text-muted mb-2">
                {detail.link.endpoint_a} ─ {detail.link.endpoint_b} · {detail.link.media} ·
                {fmt(detail.link.capacity_mbps, 0)} Mbps · {detail.sibling_sites.length} sites
              </div>
              <TimeSeries height={180} data={detail.hourly}
                series={[
                  { key: "util_pct", name: "util %", color: C.accent },
                  { key: "loss_pct", name: "loss %", color: C.bad, yAxis: 1 },
                  { key: "jitter_ms", name: "jitter ms", color: C.warn, yAxis: 1 },
                ]} />
              <div className="mt-3 text-xs uppercase text-muted">Sibling sites on this link</div>
              <div className="max-h-52 overflow-auto mt-1">
                <table className="w-full text-sm">
                  <tbody>
                    {detail.sibling_sites.map((s: any) => (
                      <tr key={s.site_id} className="border-t border-line/60 cursor-pointer hover:bg-panel2"
                          onClick={() => nav(`/sites/${s.site_id}`)}>
                        <td className="py-1">{s.site_id}</td>
                        <td><Tag kind={s.primary_attribution || "none"} /></td>
                        <td className="text-right tabular-nums">{fmt(s.impact_score, 1)}</td>
                        <td className="text-right text-muted text-xs">{s.is_priority ? `#${s.rank}` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted mt-2">
                {detail.sibling_sites.filter((s: any) => s.primary_attribution === "transport").length} of{" "}
                {detail.sibling_sites.length} sibling sites are transport-attributed — a high fraction
                confirms a common-cause fault on this link.
              </p>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
