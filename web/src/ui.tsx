import clsx from "clsx";
import { Loader2 } from "lucide-react";
import { ReactNode, useMemo, useState } from "react";

export function Card({ title, children, className, right }: {
  title?: ReactNode; children: ReactNode; className?: string; right?: ReactNode;
}) {
  return (
    <div className={clsx("card", className)}>
      {title && (
        <div className="card-h flex items-center justify-between">
          <span>{title}</span>
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" | "warn";
}) {
  return (
    <div className="card p-4">
      <div className="text-muted text-[11px] uppercase tracking-wide">{label}</div>
      <div className={clsx("text-2xl font-semibold mt-1",
        tone === "good" && "text-good", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export function Tag({ kind }: { kind: string }) {
  return <span className={clsx("tag", `tag-${kind || "none"}`)}>{kind || "none"}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-muted text-sm p-6 justify-center">
      <Loader2 className="animate-spin" size={16} /> {label || "loading…"}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="card p-4 text-bad text-sm">
      {(error as Error)?.message || "request failed"}
    </div>
  );
}

export function Bar({ value, max = 1, color = "#4d9fff" }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className="h-1.5 bg-line rounded-full overflow-hidden w-full">
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

type Col<T> = {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  sortVal?: (row: T) => number | string;
  className?: string;
  width?: number;
};

export function DataTable<T extends Record<string, any>>({
  rows, columns, initialSort, onRowClick, dense,
}: {
  rows: T[]; columns: Col<T>[]; initialSort?: { key: string; dir: "asc" | "desc" };
  onRowClick?: (row: T) => void; dense?: boolean;
}) {
  const [sort, setSort] = useState(initialSort);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const val = col?.sortVal || ((r: T) => r[sort.key]);
    return [...rows].sort((a, b) => {
      const x = val(a), y = val(b);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return sort.dir === "asc" ? c : -c;
    });
  }, [rows, sort, columns]);

  return (
    <div className="overflow-auto max-h-[70vh] rounded-lg border border-line">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className="th cursor-pointer select-none"
                style={{ width: c.width }}
                onClick={() =>
                  setSort((s) =>
                    s?.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: "desc" },
                  )
                }
              >
                {c.header}
                {sort?.key === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={i}
              className={clsx("hover:bg-panel2/70", onRowClick && "cursor-pointer")}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((c) => (
                <td key={c.key} className={clsx("td", dense && "py-1", c.className)}>
                  {c.render ? c.render(row) : String(row[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
