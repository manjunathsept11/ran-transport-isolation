import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useOverview } from "../api";
import { Card, Spinner, ErrorBox, Stat } from "../ui";
import { TimeSeries, BarChart, GeoScatter } from "../charts";
import { C, fmt, fmtInt } from "../theme";

export default function Overview() {
  const { data, isLoading, error } = useOverview();
  const nav = useNavigate();

  const points = useMemo(
    () => (data?.sites || []).map((s) => ({
      id: s.site_id, lon: s.lon, lat: s.lat,
      color: s.is_priority
        ? (({ transport: C.transport, ran: C.ran, shared: C.shared } as any)[s.primary_attribution] || C.warn)
        : "#3b475f",
      r: s.is_priority ? 6 : 3,
    })),
    [data],
  );

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  const s = data.summary;
  const mix = s.attribution_mix || {};
  const kn = data.kpi_now, kb = data.kpi_baseline;
  const delta = (k: string) => (kn[k] && kb[k] ? ((kn[k] - kb[k]) / kb[k]) * 100 : 0);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Market Overview</h1>
        <p className="text-muted text-sm">
          {s.n_sites} sites · {s.n_priority} flagged for Phase-2 audit ·{" "}
          {fmtInt(s.sessions_impacted)} sessions impacted
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Priority sites" value={s.n_priority} sub="top impact rank" />
        <Stat label="Transport-attributed" value={mix.transport || 0} tone="warn"
              sub={`${mix.ran || 0} RAN · ${mix.shared || 0} shared`} />
        <Stat label="TCP client RTT" value={`${fmt(kn.tcp_rtt, 0)} ms`}
              tone={delta("tcp_rtt") > 8 ? "bad" : "good"}
              sub={`${delta("tcp_rtt") > 0 ? "+" : ""}${fmt(delta("tcp_rtt"), 0)}% vs baseline`} />
        <Stat label="YouTube QoE" value={fmt(kn.youtube_mos, 2)}
              tone={kn.youtube_mos < 3.6 ? "bad" : "good"}
              sub={`VoNR ${fmt(kn.vonr_mos, 2)} · DL ${fmt(kn.dl_mbps, 0)} Mbps`} />
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card title="Site map — impact by attributed cause" className="lg:col-span-2">
          <div className="rounded-lg overflow-hidden border border-line">
            <GeoScatter points={points} height={380} onClick={(id) => nav(`/sites/${id}`)} />
          </div>
          <div className="flex gap-4 text-xs text-muted mt-2">
            <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: C.transport }} />transport</span>
            <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: C.ran }} />RAN</span>
            <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: C.shared }} />shared</span>
            <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: "#3b475f" }} />healthy</span>
          </div>
        </Card>

        <Card title="Priority sites by attributed cause">
          <BarChart
            height={150}
            items={[
              { name: "transport", value: mix.transport || 0, color: C.transport },
              { name: "RAN", value: mix.ran || 0, color: C.ran },
              { name: "shared", value: mix.shared || 0, color: C.shared },
              { name: "unclear", value: mix.none || 0, color: C.none },
            ]}
          />
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted">Sessions impacted</span><b>{fmtInt(s.sessions_impacted)}</b></div>
            <div className="flex justify-between"><span className="text-muted">Users impacted</span><b>{fmtInt(s.users_impacted)}</b></div>
          </div>
        </Card>
      </div>

      <Card title="Market KPI trend">
        <TimeSeries
          height={220}
          data={data.trend}
          series={[
            { key: "tcp_rtt", name: "TCP RTT (ms)", color: C.transport },
            { key: "dl_mbps", name: "DL Mbps", color: C.good, yAxis: 1 },
            { key: "youtube_mos", name: "YouTube MOS", color: C.ran, yAxis: 1 },
          ]}
        />
      </Card>
    </div>
  );
}
