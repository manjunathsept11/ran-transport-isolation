import { useIncidents } from "../api";
import { Card, Spinner, ErrorBox, Tag, Stat } from "../ui";
import { fmt } from "../theme";

export default function Incidents() {
  const { data, isLoading, error } = useIncidents();
  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  const { detected, ground_truth: gt, rca } = data;
  const matched = detected.filter((d: any) => d.match_iou > 0.2).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Incidents &amp; Root Cause</h1>
        <p className="text-muted text-sm">
          {detected.length} incidents detected from anomaly clustering · {matched} matched to ground truth ({gt.length})
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Detected incidents" value={detected.length} />
        <Stat label="Matched to truth" value={`${matched}/${gt.length}`} tone={matched >= gt.length * 0.5 ? "good" : "warn"} />
        <Stat label="RCA hypotheses" value={rca.length} />
        <Stat label="Transport-localised" value={rca.filter((r: any) => r.cause_class === "transport").length} tone="warn" />
      </div>

      <Card title="Root-cause hypotheses (transport localisation)">
        {rca.length === 0 ? (
          <div className="text-muted text-sm">No multi-site transport incidents localised in this run.</div>
        ) : (
          <div className="space-y-3">
            {rca.map((r: any, i: number) => (
              <div key={i} className="border border-line rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div className="font-medium">{r.candidate_cause}</div>
                  <div className="text-sm text-muted">confidence {fmt(r.confidence, 2)}
                    {r.matched_incident_id && <span className="text-good"> · matched {r.matched_incident_id}</span>}
                  </div>
                </div>
                <div className="text-xs text-muted font-mono mt-0.5">{r.candidate_entity}</div>
                <ul className="text-sm text-muted list-disc pl-4 mt-1">
                  {(r.evidence || []).map((e: string, j: number) => <li key={j}>{e}</li>)}
                </ul>
                <div className="text-sm mt-1"><b className="text-ink">Action:</b> {r.recommended_action}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid lg:grid-cols-2 gap-5">
        <Card title="Detected incidents">
          <table className="w-full text-sm">
            <thead><tr className="text-muted text-xs text-left"><th className="py-1">Window</th><th>Class</th><th>Sites</th><th>Sev.</th><th>IoU</th></tr></thead>
            <tbody>
              {detected.map((d: any, i: number) => (
                <tr key={i} className="border-t border-line/60">
                  <td className="py-1 text-xs">{String(d.start_ts).slice(5, 16)}</td>
                  <td><Tag kind={d.predicted_class} /></td>
                  <td>{d.n_sites}</td>
                  <td>{fmt(d.severity, 1)}</td>
                  <td className={d.match_iou > 0.2 ? "text-good" : "text-muted"}>{fmt(d.match_iou, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Ground truth incidents (demo)">
          <table className="w-full text-sm">
            <thead><tr className="text-muted text-xs text-left"><th className="py-1">ID</th><th>Class</th><th>Kind</th><th>Sites</th><th>Window</th></tr></thead>
            <tbody>
              {gt.map((g: any) => (
                <tr key={g.incident_id} className="border-t border-line/60">
                  <td className="py-1 text-xs">{g.incident_id}{g.auto_generated ? "*" : ""}</td>
                  <td><Tag kind={g.incident_class} /></td>
                  <td className="text-xs">{g.kind}</td>
                  <td>{g.n_affected_sites}</td>
                  <td className="text-xs text-muted">{String(g.start_ts).slice(5, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-muted mt-2">* auto-generated background incident</p>
        </Card>
      </div>
    </div>
  );
}
