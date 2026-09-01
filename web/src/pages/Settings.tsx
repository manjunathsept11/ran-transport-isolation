import { useEffect, useMemo, useState } from "react";
import { Play, Plus, RefreshCw, Save, Trash2, FileText } from "lucide-react";
import {
  startAnalytics, startGenerate, startReport, savePreset, useConfig, useJob, useJobs, usePresets, useStatus,
} from "../api";
import { Card, Spinner, Tag } from "../ui";

const TRANSPORT_KINDS = ["microwave_fade", "congested_backhaul", "sfp_errors", "queue_drops", "routing_flap", "mtu_blackhole", "fiber_degradation"];
const RAN_KINDS = ["sleeping_sector", "external_interference", "coverage_hole", "cell_overshoot", "prb_exhaustion", "vswr"];
const SHARED_KINDS = ["site_power_outage", "severe_weather", "transport_node_reload"];
const KINDS: Record<string, string[]> = { transport: TRANSPORT_KINDS, ran: RAN_KINDS, shared: SHARED_KINDS };

function Num({ label, value, onChange, step = 1, min, max }: any) {
  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      <input type="number" className="inp" value={value ?? ""} step={step} min={min} max={max}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
    </label>
  );
}

export default function Settings() {
  const { data: presets } = usePresets();
  const [preset, setPreset] = useState("mixed_realistic");
  const { data: loaded, refetch } = useConfig(preset);
  const [cfg, setCfg] = useState<any>(null);
  const [jobId, setJobId] = useState<string>();
  const { data: job } = useJob(jobId);
  const { data: jobs } = useJobs();
  const { data: status } = useStatus();
  const [saveName, setSaveName] = useState("");

  useEffect(() => { if (loaded) setCfg(structuredClone(loaded)); }, [loaded]);

  const running = job && (job.status === "queued" || job.status === "running");
  const busy = useMemo(() => (jobs || []).some((j) => j.status === "running" || j.status === "queued"), [jobs]);

  if (!cfg) return <Spinner label="loading config…" />;

  const set = (path: string, val: any) => {
    setCfg((c: any) => {
      const n = structuredClone(c);
      const parts = path.split(".");
      let o = n;
      for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]];
      o[parts[parts.length - 1]] = val;
      return n;
    });
  };
  const bl = (m: string) => cfg.metric_baselines?.[m]?.params || {};

  // functional updates on the incidents array (avoids stale-closure clobbering when a
  // single handler changes more than one field, e.g. class + kind together)
  const mutIncidents = (fn: (list: any[]) => any[]) =>
    setCfg((c: any) => {
      const n = structuredClone(c);
      n.incidents = fn(n.incidents || []);
      return n;
    });
  const addIncident = () =>
    mutIncidents((list) => [...list, {
      class: "transport", kind: "microwave_fade", targets: "auto", n_targets: 6,
      start_offset_hours: 48, duration_hours: 12, magnitude: 0.6,
    }]);
  const rmIncident = (i: number) => mutIncidents((list) => list.filter((_, k) => k !== i));
  const patchInc = (i: number, patch: Record<string, any>) =>
    mutIncidents((list) => list.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const setInc = (i: number, k: string, v: any) => patchInc(i, { [k]: v });

  const generate = async () => {
    const { job_id } = await startGenerate({ config: cfg, run_analytics: true });
    setJobId(job_id);
  };

  return (
    <div className="space-y-5 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold">Data Generation</h1>
        <p className="text-muted text-sm">
          Configure and run the synthetic generator. Adjust distributions and schedule labelled
          incidents, then generate — analytics runs automatically after.
        </p>
      </div>

      {/* preset picker */}
      <Card title="Preset">
        <div className="flex items-center gap-2 flex-wrap">
          <select className="inp w-auto" value={preset} onChange={(e) => setPreset(e.target.value)}>
            {(presets || []).map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
          <button className="btn" onClick={() => refetch()}><RefreshCw size={14} /> reload</button>
          <span className="text-sm text-muted">{(presets || []).find((p) => p.name === preset)?.description}</span>
        </div>
      </Card>

      <div className="grid md:grid-cols-2 gap-5">
        <Card title="Run">
          <div className="grid grid-cols-2 gap-3">
            <Num label="seed" value={cfg.seed} onChange={(v: any) => set("seed", v)} />
            <Num label="duration (days)" value={cfg.duration_days} min={1} max={45} onChange={(v: any) => set("duration_days", v)} />
            <Num label="bin seconds" value={cfg.bin_seconds} step={60} onChange={(v: any) => set("bin_seconds", v)} />
            <Num label="start date offset" value={0} onChange={() => {}} />
          </div>
        </Card>
        <Card title="Market">
          <div className="grid grid-cols-2 gap-3">
            <Num label="sites" value={cfg.market.n_sites} min={30} max={5000} onChange={(v: any) => set("market.n_sites", v)} />
            <Num label="regions" value={cfg.market.n_regions} min={1} max={20} onChange={(v: any) => set("market.n_regions", v)} />
            <Num label="microwave fraction" value={cfg.market.microwave_fraction} step={0.01} min={0} max={1}
              onChange={(v: any) => set("market.microwave_fraction", v)} />
          </div>
        </Card>
      </div>

      <Card title="Metric baselines">
        <div className="grid md:grid-cols-3 gap-3">
          <Num label="RSRP mean (dBm)" value={bl("rsrp_dbm").mean} step={1}
            onChange={(v: any) => set("metric_baselines.rsrp_dbm.params.mean", v)} />
          <Num label="RSRQ mean (dB)" value={bl("rsrq_db").mean} step={0.5}
            onChange={(v: any) => set("metric_baselines.rsrq_db.params.mean", v)} />
          <Num label="server RTT mean (ms)" value={bl("tcp_server_rtt_ms").mean} step={1}
            onChange={(v: any) => set("metric_baselines.tcp_server_rtt_ms.params.mean", v)} />
          <Num label="link base delay (ms, median)" value={bl("link_base_delay_ms").mean} step={0.1}
            onChange={(v: any) => set("metric_baselines.link_base_delay_ms.params.mean", v)} />
          <Num label="link base loss (%, median)" value={bl("link_base_loss_pct").mean} step={0.01}
            onChange={(v: any) => set("metric_baselines.link_base_loss_pct.params.mean", v)} />
          <Num label="site busy-hour erlangs (median)" value={bl("site_busy_hour_erlangs").mean} step={1}
            onChange={(v: any) => set("metric_baselines.site_busy_hour_erlangs.params.mean", v)} />
        </div>
      </Card>

      <Card title="Injected incidents (ground truth)" right={
        <button className="btn" onClick={addIncident}><Plus size={14} /> add</button>
      }>
        <div className="space-y-2">
          {(cfg.incidents || []).map((inc: any, i: number) => (
            <div key={i} className="grid grid-cols-[90px_150px_1fr_80px_80px_80px_32px] gap-2 items-end">
              <label className="block"><span className="text-[10px] text-muted">class</span>
                <select className="inp" value={inc.class}
                  onChange={(e) => {
                    const cls = e.target.value;
                    // set class AND snap kind into the new class's list, in one update
                    patchInc(i, KINDS[cls].includes(inc.kind)
                      ? { class: cls }
                      : { class: cls, kind: KINDS[cls][0] });
                  }}>
                  {Object.keys(KINDS).map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </label>
              <label className="block"><span className="text-[10px] text-muted">kind</span>
                <select className="inp" value={inc.kind} onChange={(e) => setInc(i, "kind", e.target.value)}>
                  {(KINDS[inc.class] || []).map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </label>
              <Num label="n_targets" value={inc.n_targets} onChange={(v: any) => setInc(i, "n_targets", v)} />
              <Num label="start h" value={inc.start_offset_hours} onChange={(v: any) => setInc(i, "start_offset_hours", v)} />
              <Num label="dur h" value={inc.duration_hours} onChange={(v: any) => setInc(i, "duration_hours", v)} />
              <Num label="mag" step={0.05} min={0.05} max={1} value={inc.magnitude} onChange={(v: any) => setInc(i, "magnitude", v)} />
              <button className="btn px-2 py-2" onClick={() => rmIncident(i)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-xs text-muted mb-2">
            <b className="text-ink">Auto incidents</b> — random background faults scheduled on top of the
            list above (Poisson, events per week). Set a class to <b>0</b> for full manual control —
            e.g. leave <i>transport</i> at 0 if you want no transport faults at all.
          </p>
          <div className="grid grid-cols-3 gap-3">
            <Num label="auto transport / week" step={0.1} value={cfg.auto_incidents?.transport_per_week}
              onChange={(v: any) => set("auto_incidents.transport_per_week", v)} />
            <Num label="auto RAN / week" step={0.1} value={cfg.auto_incidents?.ran_per_week}
              onChange={(v: any) => set("auto_incidents.ran_per_week", v)} />
            <Num label="auto shared / week" step={0.1} value={cfg.auto_incidents?.shared_per_week}
              onChange={(v: any) => set("auto_incidents.shared_per_week", v)} />
          </div>
        </div>
      </Card>

      {/* actions */}
      <Card title="Generate">
        <div className="flex items-center gap-2 flex-wrap">
          <button className="btn btn-primary" onClick={generate} disabled={busy}>
            <Play size={15} /> Generate + analytics
          </button>
          <button className="btn" onClick={async () => setJobId((await startAnalytics()).job_id)} disabled={busy || !status?.has_data}>
            re-run analytics
          </button>
          <button className="btn" onClick={async () => setJobId((await startReport()).job_id)} disabled={busy || !status?.has_data}>
            <FileText size={14} /> build report
          </button>
          <div className="flex items-center gap-1 ml-auto">
            <input className="inp w-40" placeholder="save as preset…" value={saveName}
              onChange={(e) => setSaveName(e.target.value)} />
            <button className="btn" disabled={!saveName}
              onClick={async () => { await savePreset(saveName, { ...cfg, name: saveName }); setSaveName(""); }}>
              <Save size={14} />
            </button>
          </div>
        </div>

        {job && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                <Tag kind={job.status === "done" ? "ran" : job.status === "error" ? "shared" : "transport"} />
                {job.message}
              </span>
              <span className="text-muted">{Math.round((job.progress || 0) * 100)}%</span>
            </div>
            <div className="h-2 bg-line rounded-full overflow-hidden mt-1">
              <div className="h-full bg-accent transition-all" style={{ width: `${(job.progress || 0) * 100}%` }} />
            </div>
            {job.status === "done" && job.result?.analytics_metrics?.attribution && (
              <p className="text-xs text-good mt-2">
                Done. Transport attribution F1:{" "}
                {(() => {
                  const e = job.result.analytics_metrics.attribution.final_vs_truth_priority
                    || job.result.analytics_metrics.attribution.final_vs_truth_all;
                  return e?.transport ? e.transport.f1.toFixed(2) : "n/a";
                })()}
              </p>
            )}
            {job.status === "error" && <p className="text-xs text-bad mt-2">{job.result?.error}</p>}
          </div>
        )}
      </Card>

      {jobs && jobs.length > 0 && (
        <Card title="Recent jobs">
          <table className="w-full text-sm">
            <tbody>
              {jobs.slice(0, 8).map((j) => (
                <tr key={j.job_id} className="border-t border-line/60">
                  <td className="py-1 font-mono text-xs">{j.job_id}</td>
                  <td>{j.kind}</td>
                  <td><Tag kind={j.status === "done" ? "ran" : j.status === "error" ? "shared" : "transport"} /></td>
                  <td className="text-muted text-xs">{j.message}</td>
                  <td className="text-right text-muted text-xs">{String(j.updated_at).slice(11, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
