import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAnomalies } from "../api";
import { Card, Spinner, ErrorBox } from "../ui";
import { Heatmap } from "../charts";

export default function Anomalies() {
  const { data, isLoading, error } = useAnomalies();
  const nav = useNavigate();

  const { xs, ys, cells } = useMemo(() => {
    const rows = data || [];
    const bySite: Record<string, Record<string, number>> = {};
    const hours = new Set<string>();
    for (const a of rows) {
      const h = String(a.peak_ts).slice(0, 13);
      hours.add(h);
      bySite[a.entity_id] = bySite[a.entity_id] || {};
      bySite[a.entity_id][h] = Math.max(bySite[a.entity_id][h] || 0, a.severity);
    }
    const ys = Object.entries(bySite)
      .sort((a, b) => Object.keys(b[1]).length - Object.keys(a[1]).length)
      .slice(0, 40)
      .map(([s]) => s);
    const xs = Array.from(hours).sort();
    const cells: [number, number, number][] = [];
    ys.forEach((s, yi) => xs.forEach((h, xi) => {
      const v = bySite[s]?.[h];
      if (v) cells.push([xi, yi, Math.min(10, v)]);
    }));
    return { xs, ys, cells };
  }, [data]);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Anomaly Explorer</h1>
        <p className="text-muted text-sm">
          {data?.length} anomaly events (STL residual + Isolation Forest / PCA) · top 40 sites by event count
        </p>
      </div>
      <Card title="Site × time anomaly severity">
        <Heatmap x={xs.map((h) => h.slice(5).replace("T", " "))} y={ys} data={cells} height={520} min={0} max={10} />
      </Card>
      <Card title="Recent anomaly events">
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-muted text-xs text-left"><th className="py-1">Site</th><th>Metric</th><th>Start</th><th>Peak σ</th><th>Method</th></tr></thead>
            <tbody>
              {(data || []).slice(0, 120).map((a: any, i: number) => (
                <tr key={i} className="border-t border-line/60 cursor-pointer hover:bg-panel2"
                    onClick={() => nav(`/sites/${a.entity_id}`)}>
                  <td className="py-1">{a.entity_id}</td>
                  <td>{a.metric}</td>
                  <td className="text-muted text-xs">{String(a.start_ts).slice(5, 16)}</td>
                  <td>{a.severity?.toFixed(1)}</td>
                  <td className="text-muted text-xs">{a.method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
