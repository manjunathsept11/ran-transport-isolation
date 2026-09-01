export const C = {
  ink: "#e6ebf2",
  muted: "#8a97ab",
  line: "#28324a",
  panel: "#161e2d",
  accent: "#4d9fff",
  transport: "#f0763c",
  ran: "#4d9fff",
  shared: "#a679e8",
  none: "#8a97ab",
  good: "#3fbf87",
  warn: "#e7b53f",
  bad: "#e35d6a",
  grid: ["#4d9fff", "#f0763c", "#3fbf87", "#a679e8", "#e7b53f", "#e35d6a"],
};

export const attrColor = (a: string) =>
  ({ transport: C.transport, ran: C.ran, shared: C.shared } as Record<string, string>)[a] || C.none;

export const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "-" : Number(v).toFixed(d);

export const fmtInt = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString();
