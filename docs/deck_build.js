/* RAN & Transport Isolation - 20-slide deck (PowerPoint-safe) */
const pptxgen = require("pptxgenjs");
const fs = require("fs");

const DIMS = JSON.parse(fs.readFileSync(`${__dirname}/img/_dims.json`, "utf8"));
const P = new pptxgen();
P.layout = "LAYOUT_WIDE";
P.author = "RAN & Transport Isolation";
P.title = "RAN & Transport Isolation Module";

const W = 13.333, H = 7.5, M = 0.62;
const C = {
  bg: "0F1626", bg2: "0B1220", card: "1A2740", card2: "223251",
  ink: "EFF4FB", ink2: "D4DEEC", sub: "97A5BD", line: "31416C",
  blue: "56A6FF", orange: "F2822F", purple: "AE82ED", mint: "45C48D", amber: "EAB63F", red: "E8687A",
};
const F = "Calibri";
const has = (n) => !!DIMS[n] && fs.existsSync(`${__dirname}/img/${n}`);

let SN = 0;
function slide(bg) {
  SN++;
  const s = P.addSlide();
  s.background = { color: bg || C.bg };
  s.addText("RAN & TRANSPORT ISOLATION", { x: M, y: H - 0.42, w: 6, h: 0.3, isTextBox: true, margin: 0, fontFace: F, fontSize: 8, color: C.sub, charSpacing: 2 });
  s.addText(`${SN} / 20`, { x: W - M - 1.2, y: H - 0.42, w: 1.2, h: 0.3, isTextBox: true, margin: 0, align: "right", fontFace: F, fontSize: 8, color: C.sub });
  return s;
}
function kicker(s, text, color) {
  s.addShape(P.ShapeType.ellipse, { x: M, y: 0.55, w: 0.14, h: 0.14, fill: { color: color || C.blue } });
  s.addText(text.toUpperCase(), { x: M + 0.26, y: 0.42, w: 10, h: 0.36, isTextBox: true, margin: 0, fontFace: F, fontSize: 11, bold: true, color: color || C.blue, charSpacing: 2 });
}
function title(s, text, sz) {
  s.addText(text, { x: M, y: 0.84, w: W - 2 * M, h: 0.9, isTextBox: true, margin: 0, fontFace: F, fontSize: sz || 31, bold: true, color: C.ink });
}
function card(s, x, y, w, h, o = {}) {
  s.addShape(P.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: o.fill || C.card }, line: { color: o.line || C.line, width: o.lw == null ? 0.75 : o.lw } });
}
function chip(s, x, y, w, text, color) {
  s.addShape(P.ShapeType.roundRect, { x, y, w, h: 0.4, rectRadius: 0.14, fill: { color: C.card2 }, line: { color, width: 1 } });
  s.addText(text, { x, y, w, h: 0.4, isTextBox: true, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 10.5, bold: true, color });
}
function numCircle(s, x, y, d, n, color) {
  s.addShape(P.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: C.bg }, line: { color, width: 1.5 } });
  s.addText(String(n), { x, y, w: d, h: d, isTextBox: true, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: d > 0.42 ? 14 : 11, bold: true, color });
}
function para(s, x, y, w, h, text, o = {}) {
  s.addText(text, { x, y, w, h, isTextBox: true, margin: 0, valign: o.valign || "top", align: o.align || "left", fontFace: F, fontSize: o.size || 13, color: o.color || C.ink2, lineSpacingMultiple: o.lsm || 1.16 });
}
function bullets(s, x, y, w, h, items, o = {}) {
  const runs = items.map((t, i) => ({ text: t, options: { bullet: { code: "2022", indent: 12 }, breakLine: i < items.length - 1, paraSpaceAfter: o.gap == null ? 7 : o.gap } }));
  s.addText(runs, { x, y, w, h, isTextBox: true, margin: 0, valign: "top", fontFace: F, fontSize: o.size || 12.5, color: o.color || C.ink2, lineSpacingMultiple: 1.08 });
}
// PowerPoint-safe connectors: bounding box always has non-zero cx and cy
function hArrow(s, x, y, w, color) {
  s.addShape(P.ShapeType.line, { x, y, w: Math.max(w, 0.05), h: 0.03, line: { color: color || C.line, width: 1.5, endArrowType: "triangle" } });
}
function connect(s, x1, y1, x2, y2, color) {
  const x = Math.min(x1, x2), y = Math.min(y1, y2);
  s.addShape(P.ShapeType.line, { x, y, w: Math.max(Math.abs(x2 - x1), 0.04), h: Math.max(Math.abs(y2 - y1), 0.04),
    flipH: x2 < x1, flipV: y2 < y1, line: { color: color || C.line, width: 1.1 } });
}
function router(s, x, y, w, color, label) {
  s.addShape(P.ShapeType.roundRect, { x, y, w, h: 0.4, rectRadius: 0.07, fill: { color: C.card2 }, line: { color, width: 1.4 } });
  if (label) s.addText(label, { x, y, w, h: 0.4, isTextBox: true, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 8.5, bold: true, color: C.ink2 });
}
function tower(s, x, y, sc, color) {
  s.addShape(P.ShapeType.triangle, { x, y, w: 0.5 * sc, h: 0.68 * sc, fill: { color: C.bg }, line: { color, width: 2 } });
  s.addShape(P.ShapeType.line, { x: x + 0.25 * sc, y: y + 0.68 * sc, w: 0.02, h: 0.32 * sc, line: { color, width: 2 } });
  s.addShape(P.ShapeType.ellipse, { x: x + 0.19 * sc, y: y - 0.13 * sc, w: 0.12 * sc, h: 0.12 * sc, fill: { color } });
}
function shot(s, name, x, y, boxW, boxH, cap) {
  if (has(name)) {
    const [iw, ih] = DIMS[name];
    const r = Math.min(boxW / iw, boxH / ih);
    const w = iw * r, h = ih * r;
    const ix = x + (boxW - w) / 2, iy = y + (boxH - h) / 2;
    s.addShape(P.ShapeType.roundRect, { x: ix - 0.05, y: iy - 0.05, w: w + 0.1, h: h + 0.1, rectRadius: 0.03, fill: { color: C.card2 }, line: { color: C.line, width: 1 } });
    s.addImage({ path: `img/${name}`, x: ix, y: iy, w, h });
    if (cap) s.addText(cap, { x, y: y + boxH + 0.06, w: boxW, h: 0.3, isTextBox: true, margin: 0, fontFace: F, fontSize: 9, italic: true, color: C.sub });
  } else {
    card(s, x, y, boxW, boxH, { fill: C.card2 });
    s.addText(`[${name}]`, { x, y, w: boxW, h: boxH, isTextBox: true, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 12, color: C.sub });
  }
}
function callout(s, x, y, w, text, color) {
  s.addShape(P.ShapeType.roundRect, { x, y, w, h: 0.52, rectRadius: 0.09, fill: { color: C.bg2 }, line: { color: color || C.blue, width: 1 } });
  s.addText(text, { x: x + 0.14, y, w: w - 0.28, h: 0.52, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 10, color: C.ink2 });
}

/* ============ 1 · TITLE ============ */
{
  const s = slide(C.bg2);
  s.addText("RAN & Transport", { x: M, y: 1.65, w: 9.4, h: 1.0, isTextBox: true, margin: 0, fontFace: F, fontSize: 50, bold: true, color: C.ink });
  s.addText("Isolation Module", { x: M, y: 2.62, w: 9.4, h: 1.0, isTextBox: true, margin: 0, fontFace: F, fontSize: 50, bold: true, color: C.orange });
  s.addText("Rank the sites, nodes and transport paths most impacted by transport-network problems — and tell you which are transport vs RAN, with the evidence.",
    { x: M, y: 3.85, w: 8.7, h: 1.0, isTextBox: true, margin: 0, fontFace: F, fontSize: 15.5, color: C.sub, lineSpacingMultiple: 1.2 });
  ["IP Transport Analytics", "Impact Analytics Dashboard", "Phase-2 Audit Prioritisation"].forEach((t, i) => chip(s, M + i * 3.15, 5.15, 3.0, t, C.blue));
  s.addText("Synthetic-data build  ·  standalone web app  ·  github.com/manjunathsept11/ran-transport-isolation",
    { x: M, y: 6.5, w: 11, h: 0.3, isTextBox: true, margin: 0, fontFace: F, fontSize: 10, color: C.sub });
  const gx = 10.55;
  connect(s, gx + 1.05, 1.95, gx + 0.25, 2.5, C.line);
  connect(s, gx + 1.05, 1.95, gx + 1.15, 2.5, C.line);
  connect(s, gx + 1.05, 1.95, gx + 2.05, 2.5, C.line);
  for (let i = 0; i < 6; i++) connect(s, gx + 0.25 + (i < 3 ? 0 : i < 4 ? 0.9 : 1.8), 2.9, gx - 0.13 + i * 0.44 + 0.13, 3.7, C.line);
  router(s, gx + 0.5, 1.55, 1.1, C.blue, "CORE");
  [0, 1, 2].forEach((i) => router(s, gx - 0.15 + i * 0.9, 2.5, 0.8, C.blue, "AGG"));
  for (let i = 0; i < 6; i++) tower(s, gx - 0.13 + i * 0.44, 3.72, 0.48, C.orange);
  s.addNotes("Rank transport-impacted sites and separate transport vs RAN causes, with explainable evidence. Synthetic data now; live feeds later.");
}

/* ============ 2 · USE CASE ============ */
{
  const s = slide();
  kicker(s, "The use case", C.blue);
  title(s, "Correlate experience with transport — then rank and attribute");
  para(s, M, 1.9, 6.2, 2.4, "Ingest and correlate end-user experience metrics with transport-layer telemetry to identify and rank the sites, nodes and transport paths most impacted — and separate transport-attributed impairment from RAN-attributed impairment using serving-cell context and radio signal quality.", { size: 14, lsm: 1.22 });
  [["5", "data feeds\nstitched"], ["7", "analytics\nmodules"], ["75–100", "sites for the\nPhase-2 audit"], ["0", "LLM calls in\nthe runtime"]].forEach(([n, l], i) => {
    const x = M + i * 1.55;
    card(s, x, 4.55, 1.4, 1.55);
    s.addText(n, { x, y: 4.68, w: 1.4, h: 0.7, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 22, bold: true, color: C.orange });
    s.addText(l, { x, y: 5.38, w: 1.4, h: 0.65, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 8.5, color: C.sub, lineSpacingMultiple: 1.05 });
  });
  card(s, 7.4, 1.9, W - M - 7.4, 4.35);
  s.addText("Deliverables", { x: 7.68, y: 2.08, w: 5, h: 0.4, isTextBox: true, margin: 0, fontFace: F, fontSize: 15, bold: true, color: C.ink });
  bullets(s, 7.68, 2.62, W - M - 7.68 - 0.3, 3.5, [
    "Impact analytics dashboard ranking sites, nodes and transport paths",
    "Headline KPIs: TCP RTT, TCP Fail %, Ookla throughput, VoNR MOS, YouTube QoE",
    "Prioritised list of the top 75–100 sites for a Phase-2 field audit (CSV / Excel)",
    "Per-site root-cause indicators and a recommended technician action",
    "Transport-attributed impairment distinguished from RAN-attributed",
  ], { size: 12, gap: 11 });
  s.addNotes("Straight from the brief. Outputs: ranked dashboard, exportable audit shortlist, per-site root-cause + action.");
}

/* ============ 3 · THE PROBLEM ============ */
{
  const s = slide();
  kicker(s, "The problem", C.orange);
  title(s, "Users complain. Whose problem is it?");
  const y = 2.35;
  s.addShape(P.ShapeType.roundRect, { x: M, y, w: 1.3, h: 1.25, rectRadius: 0.12, fill: { color: C.card2 }, line: { color: C.blue, width: 1.4 } });
  s.addText("user", { x: M, y: y + 0.9, w: 1.3, h: 0.3, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 8.5, color: C.sub });
  tower(s, M + 2.25, y + 0.15, 0.95, C.blue);
  s.addText("RAN", { x: M + 1.95, y: y + 1.1, w: 1.4, h: 0.3, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 8.5, color: C.sub });
  router(s, M + 4.1, y + 0.2, 1.0, C.orange, "PA"); router(s, M + 4.1, y + 0.72, 1.0, C.orange, "AGG");
  s.addText("transport", { x: M + 3.9, y: y + 1.18, w: 1.4, h: 0.3, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 8.5, color: C.sub });
  s.addShape(P.ShapeType.ellipse, { x: M + 6.0, y: y + 0.22, w: 1.45, h: 0.9, fill: { color: C.card2 }, line: { color: C.sub, width: 1.2 } });
  s.addText("internet", { x: M + 6.0, y: y + 1.18, w: 1.45, h: 0.3, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 8.5, color: C.sub });
  hArrow(s, M + 1.35, y + 0.62, 0.8, C.line); hArrow(s, M + 3.3, y + 0.62, 0.75, C.line); hArrow(s, M + 5.15, y + 0.62, 0.8, C.line);
  s.addText("?", { x: M + 2.1, y: y - 0.7, w: 0.7, h: 0.7, isTextBox: true, margin: 0, align: "center", fontFace: F, fontSize: 30, bold: true, color: C.amber });
  const cy = 4.1;
  card(s, M, cy, 5.9, 2.35, { line: C.blue });
  s.addText("Looks like RAN", { x: M + 0.25, y: cy + 0.15, w: 5, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 13, bold: true, color: C.blue });
  bullets(s, M + 0.25, cy + 0.62, 5.4, 1.6, ["Coverage hole / poor RSRP", "Interference, low RSRQ", "PRB exhaustion at busy hour", "Sleeping sector, VSWR / feeder fault"], { size: 11.5, gap: 4 });
  card(s, M + 6.3, cy, 5.9, 2.35, { line: C.orange });
  s.addText("Looks like Transport", { x: M + 6.55, y: cy + 0.15, w: 5, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 13, bold: true, color: C.orange });
  bullets(s, M + 6.55, cy + 0.62, 5.4, 1.6, ["Fibre degradation, microwave fade", "Backhaul congestion at busy hour", "SFP / CRC errors, queue drops", "Routing flap, MTU black-hole"], { size: 11.5, gap: 4 });
  s.addText("Same symptom — high latency, buffering, dropped calls — two different owners, two different fixes.", { x: M, y: 6.68, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 12, italic: true, color: C.ink2 });
  s.addNotes("Same user symptom, two possible owners, two different fixes. Today the split is a manual, cross-team argument.");
}

/* ============ 4 · PAIN POINTS ============ */
{
  const s = slide();
  kicker(s, "Pain points today", C.orange);
  title(s, "Manual, siloed, and unmeasurable");
  const items = [
    ["Siloed data", "Ookla, N3 probes, TWAMP, SevOne each live in their own tool — no single correlated view."],
    ["Manual triage", "Engineers eyeball KPI graphs site by site. It does not scale to a whole market."],
    ["Finger-pointing", "RAN and transport teams each say ‘not us’; tickets bounce between them for days."],
    ["No prioritisation", "Which 80 sites do we audit first? Today that answer is gut feel."],
    ["No ground truth", "There is no way to check whether the triage call was actually right."],
    ["Slow Phase-2 audits", "Shortlisting sites for field work takes weeks of cross-team analysis."],
  ];
  const cw = (W - 2 * M - 0.6) / 3, ch = 2.05;
  items.forEach((it, i) => {
    const x = M + (i % 3) * (cw + 0.3), y = 2.0 + Math.floor(i / 3) * (ch + 0.35);
    card(s, x, y, cw, ch);
    s.addShape(P.ShapeType.ellipse, { x: x + 0.25, y: y + 0.25, w: 0.32, h: 0.32, fill: { color: C.orange } });
    s.addText(it[0], { x: x + 0.7, y: y + 0.2, w: cw - 0.9, h: 0.44, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: C.ink });
    para(s, x + 0.25, y + 0.74, cw - 0.5, ch - 0.9, it[1], { size: 10.5, lsm: 1.12 });
  });
  s.addNotes("Six concrete pain points the module removes.");
}

/* ============ 5 · DATA USED ============ */
{
  const s = slide();
  kicker(s, "The data", C.blue);
  title(s, "Five feeds, one timeline");
  const feeds = [
    ["Ookla SpeedTest", "user experience + radio", "UL/DL throughput, loaded latency, RSRP, RSRQ", C.blue],
    ["N3 probe EDRs", "session — the split point", "TCP client RTT, TCP server RTT, TCP fail %, retransmissions, VoNR MOS", C.orange],
    ["YouTube / Audio QoE", "application", "video / audio MOS, rebuffer ratio, startup delay", C.purple],
    ["TWAMP", "pure transport (active probes on each link)", "one-way / round-trip delay, frame loss, jitter", C.mint],
    ["SevOne", "transport devices", "router queue depth, discards, interface utilisation, CRC errors", C.amber],
  ];
  let y = 1.82; const rh = 0.82;
  feeds.forEach(([n, layer, fields, col]) => {
    card(s, M, y, W - 2 * M, rh);
    s.addShape(P.ShapeType.roundRect, { x: M + 0.18, y: y + 0.14, w: 0.15, h: rh - 0.28, rectRadius: 0.06, fill: { color: col } });
    s.addText(n, { x: M + 0.52, y: y + 0.06, w: 2.9, h: 0.36, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, color: C.ink });
    s.addText(layer, { x: M + 0.52, y: y + 0.42, w: 3.2, h: 0.32, isTextBox: true, margin: 0, fontFace: F, fontSize: 9.3, italic: true, color: col });
    s.addText(fields, { x: M + 3.95, y, w: W - 2 * M - 4.15, h: rh, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, color: C.ink2 });
    y += rh + 0.12;
  });
  s.addText("Joined on  site  ·  cell  ·  transport-path  ·  5-minute bin.", { x: M, y: y + 0.06, w: 10, h: 0.32, isTextBox: true, margin: 0, fontFace: F, fontSize: 11.5, italic: true, color: C.sub });
  s.addNotes("The five feeds and what each contributes. The N3 probe's client-vs-server RTT split is the key one for isolation.");
}

/* ============ 6 · STITCHING ============ */
{
  const s = slide();
  kicker(s, "One unified timeline", C.blue);
  title(s, "From five raw feeds to one feature table");
  const steps = [
    ["Serving-cell resolution", "each Ookla / QoE test → its serving site by reported cell id, else geo + strongest RSRP; low-confidence matches flagged"],
    ["Topology join", "site → transport path → its access, pre-agg and agg links → the TWAMP sessions and SevOne interfaces on them"],
    ["Temporal alignment", "every feed bucketed to the same 5-minute grid, then rolled up hourly for the dashboard"],
    ["Feature table", "one row per (site, hour): radio, session, app and transport-path KPIs together"],
    ["Robust baselines", "deviation vs the site's own trailing median / inter-decile range AND its morphology + load peer group"],
  ];
  steps.forEach((st, i) => {
    const y = 1.95 + i * 0.95;
    numCircle(s, M, y, 0.44, i + 1, C.blue);
    s.addText(st[0], { x: M + 0.66, y: y - 0.1, w: 3.5, h: 0.62, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, color: C.ink });
    para(s, M + 4.25, y - 0.15, W - M - 4.25 - 0.1, 0.75, st[1], { size: 10.5, lsm: 1.12, valign: "middle" });
    if (i < steps.length - 1) connect(s, M + 0.22, y + 0.46, M + 0.22, y + 0.9, C.line);
  });
  s.addNotes("The stitching layer. Serving-cell resolution and the topology join are what make sibling-site correlation possible.");
}

/* ============ 7 · ARCHITECTURE ============ */
{
  const s = slide();
  kicker(s, "Solution architecture", C.blue);
  title(s, "One pipeline — batch now, streaming later");
  const steps = ["Feeds", "Stitch &\nalign", "Feature\ntable", "Score &\nrank", "Attribute\ntransport / RAN", "Localise\n(graph RCA)", "Dashboard\n+ audit list"];
  const n = steps.length, cw = (W - 2 * M) / n;
  steps.forEach((t, i) => {
    const x = M + i * cw;
    s.addShape(P.ShapeType.chevron, { x, y: 2.0, w: cw + 0.02, h: 1.1, fill: { color: i === n - 1 ? C.orange : C.card2 }, line: { color: i === n - 1 ? C.orange : C.line, width: 1 } });
    s.addText(t, { x: x + 0.15, y: 2.0, w: cw - 0.2, h: 1.1, isTextBox: true, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 9.5, bold: true, color: i === n - 1 ? "0F1626" : C.ink2 });
  });
  const hw = (W - 2 * M - 0.5) / 2;
  card(s, M, 3.75, hw, 2.4, { line: C.blue });
  s.addText("Now — batch", { x: M + 0.25, y: 3.9, w: 5, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 13, bold: true, color: C.blue });
  bullets(s, M + 0.25, 4.34, hw - 0.5, 1.8, [
    "Synthetic generator writes the SQLite warehouse + Parquet raw layer",
    "na generate → na analytics → na report  (or the Settings page)",
    "Dashboard reads pre-computed serving tables — always fast",
  ], { size: 10.5, gap: 7 });
  const rx = M + hw + 0.5;
  card(s, rx, 3.75, hw, 2.4, { line: C.mint });
  s.addText("Live — streaming (Phase 2)", { x: rx + 0.25, y: 3.9, w: 5, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 13, bold: true, color: C.mint });
  bullets(s, rx + 0.25, 4.34, hw - 0.5, 1.8, [
    "The five feeds land continuously via the data-acquisition / ingestion layer",
    "5-min rollups on arrival; analytics recompute on a schedule (e.g. hourly)",
    "Same serving tables, same dashboard — plus alerting on new priority sites",
  ], { size: 10.5, gap: 7 });
  s.addText("SQLite warehouse  ·  FastAPI backend  ·  React dashboard  ·  background job runner", { x: M, y: 6.42, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 10.5, color: C.sub });
  s.addNotes("Same pipeline for synthetic and live data; only the source and cadence change. The dashboard never runs analytics inline.");
}

/* ============ 8 · ISOLATION LOGIC ============ */
{
  const s = slide();
  kicker(s, "How isolation works", C.orange);
  title(s, "Transport vs RAN — the tell");
  const cards = [
    ["1  The RTT split", "TCP client RTT = radio + the whole transport path (round trip). TCP server RTT = internet only, site-independent — the control.", "Client RTT up while server RTT flat  →  access / transport, not the internet.", C.blue],
    ["2  Signature match", "Radio: RSRP / RSRQ degraded, PRB near 100 %, usually one sector. Transport: TWAMP loss / jitter, SevOne queue / CRC, per-link delay — the transport layer's own instruments.", "Pure-transport instruments lit, radio clean  →  transport.", C.orange],
    ["3  Common cause", "A single radio fault cannot degrade 18 sites at once. A shared backhaul link does it every time.", "‘% of sibling sites on the shared uplink also degraded’ is the strongest tell.", C.mint],
  ];
  const cw = (W - 2 * M - 0.6) / 3;
  cards.forEach(([h, b, k, col], i) => {
    const x = M + i * (cw + 0.3);
    card(s, x, 1.95, cw, 3.15, { line: col });
    s.addText(h, { x: x + 0.25, y: 2.12, w: cw - 0.5, h: 0.4, isTextBox: true, margin: 0, fontFace: F, fontSize: 14, bold: true, color: col });
    para(s, x + 0.25, 2.58, cw - 0.5, 1.55, b, { size: 10.6, lsm: 1.15 });
    s.addShape(P.ShapeType.roundRect, { x: x + 0.2, y: 4.18, w: cw - 0.4, h: 0.76, rectRadius: 0.07, fill: { color: C.bg2 }, line: { color: col, width: 1 } });
    s.addText(k, { x: x + 0.35, y: 4.18, w: cw - 0.7, h: 0.76, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 9.5, bold: true, color: C.ink2, lineSpacingMultiple: 1.05 });
  });
  ["transport", "RAN", "shared", "unclear"].forEach((v, i) => chip(s, M + i * 2.35, 5.5, 2.05, v, [C.orange, C.blue, C.purple, C.sub][i]));
  s.addText("+  a calibrated confidence score", { x: M + 4 * 2.35 + 0.15, y: 5.5, w: 4, h: 0.4, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 10.5, italic: true, color: C.sub });
  s.addText("Any one alone is weak — together they give a class and a confidence.", { x: M, y: 6.3, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 11.5, italic: true, color: C.sub });
  s.addNotes("Three independent tests → a class plus a calibrated confidence.");
}

/* ============ 9 · IMPACT SCORING ============ */
{
  const s = slide();
  kicker(s, "Ranking", C.blue);
  title(s, "Impact scoring — which sites, in what order");
  const rows = [
    ["Per-KPI severity", "robust exceedance of each headline KPI vs its baseline, session-weighted"],
    ["Composite score", "normalise each severity, then a weighted blend over the 5 headline KPIs"],
    ["Impact weighting", "× sessions impacted  × users impacted  (from the raw session records)"],
    ["Worst window", "the 6-hour span with the largest summed degradation — where to look"],
    ["Priority slice", "top ≈ 75–120 by impact → flagged for the Phase-2 audit, exportable to Excel"],
  ];
  rows.forEach(([k, v], i) => {
    const y = 1.95 + i * 0.82;
    card(s, M, y, W - 2 * M, 0.7);
    s.addText(k, { x: M + 0.25, y, w: 2.7, h: 0.7, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: C.blue });
    s.addText(v, { x: M + 3.2, y, w: W - 2 * M - 3.4, h: 0.7, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 11, color: C.ink2 });
  });
  s.addText("Ranking is deliberately transparent — a weighted composite, not a black box — so an engineer can see why a site is at #3.",
    { x: M, y: 6.35, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 11.5, italic: true, color: C.sub });
  s.addNotes("Impact = severity × sessions/users impacted, blended across the headline KPIs. Transparent by design.");
}

/* ============ 10 · ATTRIBUTION ENGINE ============ */
{
  const s = slide();
  kicker(s, "Attribution engine", C.orange);
  title(s, "Rules ∪ LightGBM + SHAP, calibrated ensemble");
  const stages = [
    ["Rule engine", C.orange, "deterministic thresholds on the robust-z features; separates pure-transport signals from ambiguous ones; emits a class + a plain-English evidence list"],
    ["LightGBM classifier", C.blue, "gradient-boosted trees, multiclass, class-weight balanced, trained on the injected ground-truth labels per (site, hour)"],
    ["SHAP", C.purple, "Shapley values on the booster → the top features that drove each per-site call, shown as bars"],
    ["Calibrated ensemble", C.mint, "isotonic-calibrated; rule + ML combined, with a guardrail so a confident RAN rule beats an over-eager transport ML vote"],
  ];
  stages.forEach(([h, col, b], i) => {
    const y = 1.95 + i * 1.12;
    card(s, M, y, W - 2 * M, 0.98, { line: col });
    s.addText(h, { x: M + 0.25, y: y + 0.11, w: 3.4, h: 0.34, isTextBox: true, margin: 0, fontFace: F, fontSize: 12.5, bold: true, color: col });
    para(s, M + 0.25, y + 0.45, W - 2 * M - 0.5, 0.5, b, { size: 9.8, lsm: 1.08 });
  });
  s.addText("Evaluated against ground truth every run: precision / recall / F1 per class, confusion matrix — reported in the dashboard and the notebook.",
    { x: M, y: 6.5, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 10.5, italic: true, color: C.sub });
  s.addNotes("Explainable-first: rules + SHAP + evidence text. LightGBM adds lift. Ensemble is isotonic-calibrated. No LLM.");
}

/* ============ 11 · SUPPORTING ANALYTICS ============ */
{
  const s = slide();
  kicker(s, "Supporting analytics", C.blue);
  title(s, "Anomaly · correlation · variability");
  const cols = [
    ["Anomaly detection", C.orange, ["STL seasonal-residual + robust threshold, per KPI series", "Isolation Forest + PCA reconstruction error, multivariate", "clustered by time + topology into candidate incidents", "matched to ground truth by site-set IoU"]],
    ["Correlation", C.blue, ["Spearman + partial correlation between KPI pairs", "lead / lag cross-correlation — finds precursors", "e.g. SevOne queue buildup leads the QoE drop", "per-site layer driver split (transport vs radio)"]],
    ["Variability", C.mint, ["variance components: site / hour / day / residual", "CV, IQR, busy-hour vs off-peak spread", "PSI drift, week over week", "flags high-variance / acceptable-mean sites"]],
  ];
  const cw = (W - 2 * M - 0.6) / 3;
  cols.forEach(([h, col, items], i) => {
    const x = M + i * (cw + 0.3);
    card(s, x, 1.95, cw, 2.75, { line: col });
    s.addText(h, { x: x + 0.22, y: 2.12, w: cw - 0.4, h: 0.4, isTextBox: true, margin: 0, fontFace: F, fontSize: 13, bold: true, color: col });
    bullets(s, x + 0.22, 2.66, cw - 0.44, 3.3, items, { size: 9.6, gap: 8 });
  });
  s.addNotes("These do not attribute a cause on their own - they corroborate the attribution and surface intermittent faults.");
}

/* ============ 12 · ROOT-CAUSE LOCALISATION ============ */
{
  const s = slide();
  kicker(s, "Root cause", C.orange);
  title(s, "Localise the fault to a link");
  para(s, M, 1.95, 6.1, 2.2, "The transport network is a tree in a networkx graph. Given the set of sites degraded together in one window, a greedy minimal hitting set finds the smallest set of shared links whose failure explains every one of them — a Noisy-OR-style fault localisation.", { size: 13, lsm: 1.2 });
  bullets(s, M, 3.75, 6.1, 2.2, [
    "Combines attribution + anomaly cluster + changepoint timing + topology",
    "Confidence = fraction of affected sites the hitting set explains",
    "Matched to ground truth (demo) and given a recommended technician action",
  ], { size: 11, gap: 8 });
  const gx = 8.4, gw = W - M - gx;
  card(s, gx, 1.95, gw, 4.4);
  const cx = gx + gw / 2;
  router(s, cx - 0.55, 2.3, 1.1, C.blue, "AGG");
  [-1.4, 0, 1.4].forEach((dx) => { router(s, cx + dx - 0.45, 3.2, 0.9, C.blue, "PA"); connect(s, cx, 2.7, cx + dx, 3.2, C.line); });
  for (let i = 0; i < 9; i++) { const dx = -2.0 + i * 0.5; tower(s, cx + dx, 4.15, 0.42, i >= 3 && i <= 5 ? C.orange : C.sub); }
  // highlight the faulted PA→AGG link
  s.addShape(P.ShapeType.line, { x: cx - 0.02, y: 2.7, w: 0.04, h: 0.5, line: { color: C.orange, width: 3 } });
  s.addText("one PA→AGG link  →  9 sites degrade together  →  hitting set = 1 link", { x: gx + 0.25, y: 5.4, w: gw - 0.5, h: 0.7, isTextBox: true, margin: 0, fontFace: F, fontSize: 9.5, bold: true, color: C.orange, lineSpacingMultiple: 1.1 });
  s.addNotes("Transport localisation is a graph problem: minimal set of shared links covering the affected-site set.");
}

/* ============ 13 · WHY SYNTHETIC ============ */
{
  const s = slide();
  kicker(s, "The data engine", C.mint);
  title(s, "The data is synthetic — on purpose");
  card(s, M, 1.95, 5.5, 4.3);
  s.addText("Why", { x: M + 0.25, y: 2.12, w: 4, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 14, bold: true, color: C.ink });
  bullets(s, M + 0.25, 2.6, 5.0, 3.4, [
    "Data-pipeline engineering is not in scope yet — real feeds arrive in Phase 2.",
    "A simulator lets us build and validate the analytics against known answers.",
    "Labelled fault injection → every record has a ground-truth cause.",
    "So precision / recall of the attribution is a real, reported number.",
  ], { size: 11.5, gap: 11 });
  const rx = 6.5, rw = W - M - rx;
  card(s, rx, 1.95, rw, 4.3);
  s.addText("The layered causal model", { x: rx + 0.25, y: 2.12, w: 5, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 14, bold: true, color: C.ink });
  [["Demand", "diurnal + weekly load shape", C.sub],
   ["Radio", "path loss → RSRP · load → PRB · interference → RSRQ", C.blue],
   ["Transport", "M/M/1 queueing on shared links → delay / jitter / loss", C.orange],
   ["Session / App", "TCP RTT, throughput, VoNR MOS (E-model), YouTube QoE", C.mint]].forEach(([n2, d, col], i) => {
    const y = 2.62 + i * 0.82;
    s.addShape(P.ShapeType.roundRect, { x: rx + 0.25, y, w: rw - 0.5, h: 0.7, rectRadius: 0.06, fill: { color: C.card2 }, line: { color: col, width: 1 } });
    s.addText(n2, { x: rx + 0.42, y, w: 1.7, h: 0.7, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, color: col });
    s.addText(d, { x: rx + 2.1, y, w: rw - 2.45, h: 0.7, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 9.6, color: C.ink2 });
    if (i < 3) connect(s, rx + 0.25 + (rw - 0.5) / 2, y + 0.7, rx + 0.25 + (rw - 0.5) / 2, y + 0.82, C.line);
  });
  s.addText("Every metric is derived from shared latent state — so the KPI correlations are physical, not bolted-on noise.", { x: M, y: 6.5, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 11, italic: true, color: C.sub });
  s.addNotes("Synthetic is the only way to measure attribution accuracy. The causal model makes correlations realistic.");
}

/* ============ 14 · GENERATION STAGES ============ */
{
  const s = slide();
  kicker(s, "Data generation", C.mint);
  title(s, "Six stages — seeded and reproducible");
  const stages = [
    ["Topology", "market → regions → sites → cells; routers; links; per-site 3-hop path"],
    ["Incidents", "explicit + Poisson auto faults, resolved to targets & a time window — the GROUND TRUTH"],
    ["Causal metric model", "per 5-min bin: demand → queueing → radio → session / app KPIs, with incident state-deltas injected first"],
    ["Raw sessions", "a Poisson count of individual Ookla tests / QoE sessions per site-bin, with per-session noise"],
    ["Hourly rollups", "5-min parquet → hourly; transport link metrics rolled along each site's path"],
    ["Load", "SQLite warehouse: dimensions, ground truth, hourly rollups, raw sessions"],
  ];
  stages.forEach((st, i) => {
    const y = 1.95 + i * 0.78;
    numCircle(s, M, y, 0.42, i + 1, C.mint);
    s.addText(st[0], { x: M + 0.62, y: y - 0.1, w: 2.9, h: 0.6, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: C.ink });
    para(s, M + 3.65, y - 0.13, W - M - 3.65 - 0.1, 0.7, st[1], { size: 10, lsm: 1.08, valign: "middle" });
    if (i < stages.length - 1) connect(s, M + 0.2, y + 0.44, M + 0.2, y + 0.78, C.line);
  });
  s.addText("~1,200 sites  ·  ~1,450 links  ·  5-minute granularity  ·  1–2 weeks  ·  same seed → byte-identical dataset", { x: M, y: 6.7, w: W - 2 * M, h: 0.32, isTextBox: true, margin: 0, fontFace: F, fontSize: 10.5, color: C.sub });
  s.addNotes("Six generation stages. Determinism verified by row-count and hash checksum.");
}

/* ============ 15 · TOPOLOGY ============ */
{
  const s = slide();
  kicker(s, "Network model", C.blue);
  title(s, "A 3-tier transport tree with shared uplinks");
  const gx = M, gw = 6.6;
  card(s, gx, 1.95, gw, 4.4);
  const cx = gx + gw / 2;
  router(s, cx - 0.6, 2.35, 1.2, C.blue, "CORE");
  [-1.8, 0, 1.8].forEach((dx) => { router(s, cx + dx - 0.45, 3.25, 0.9, C.blue, "AGG"); connect(s, cx, 2.75, cx + dx, 3.25, C.line); });
  [-2.4, -1.6, -0.75, 0.1, 0.95, 1.75].forEach((dx, i) => { router(s, cx + dx - 0.3, 4.15, 0.62, C.blue, "PA"); connect(s, cx + (i < 2 ? -1.8 : i < 4 ? 0 : 1.8), 3.65, cx + dx, 4.15, C.line); });
  for (let i = 0; i < 12; i++) tower(s, cx - 2.7 + i * 0.46, 5.0, 0.34, C.orange);
  s.addText("site → access link → PA → PA-uplink → AGG → AGG-uplink → core", { x: gx + 0.25, y: 5.55, w: gw - 0.5, h: 0.6, isTextBox: true, margin: 0, fontFace: F, fontSize: 9, italic: true, color: C.sub });
  const rx = 7.4;
  bullets(s, rx, 2.0, W - M - rx, 4.4, [
    "Access link: serves 1 site (fibre or microwave)",
    "PA uplink: serves a whole cluster (~18 sites)",
    "AGG uplink: serves a whole region",
    "One PA-uplink fault degrades ~18 sites at once — that is the common-cause signature the analytics keys on",
    "No redundant paths: a fault has a clean, known blast radius to score against",
    "3 sectors × 1–3 carriers per site; band plan by morphology",
  ], { size: 11.5, gap: 10 });
  s.addNotes("Classic aggregation tree. Shared uplinks give transport faults a clean blast radius and enable sibling-site correlation.");
}

/* ============ 16 · METHODS ============ */
{
  const s = slide();
  kicker(s, "Methods", C.blue);
  title(s, "Statistical, ML and graph — explainable first");
  const rows = [
    ["Baselining", "robust trailing median + inter-decile range; morphology + load peer-group z-scores"],
    ["Impact scoring", "weighted multi-criteria composite; session- and user-impacted weighting"],
    ["Attribution", "rule engine ∪ LightGBM (gradient-boosted trees) + SHAP; isotonic-calibrated ensemble"],
    ["Anomaly", "STL residual + Isolation Forest + PCA reconstruction error; time + topology clustering"],
    ["Correlation", "Spearman, partial correlation (precision matrix), lead / lag cross-correlation"],
    ["Variability", "variance components, coefficient of variation, PSI drift (week over week)"],
    ["Root cause", "networkx transport graph + minimal hitting set (Noisy-OR fault localisation)"],
  ];
  let y = 1.86;
  rows.forEach(([k, v]) => {
    card(s, M, y, W - 2 * M, 0.55);
    s.addText(k, { x: M + 0.2, y, w: 2.3, h: 0.55, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 12, bold: true, color: C.blue });
    s.addText(v, { x: M + 2.7, y, w: W - 2 * M - 2.9, h: 0.55, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 10.5, color: C.ink2 });
    y += 0.63;
  });
  s.addShape(P.ShapeType.roundRect, { x: M, y: y + 0.05, w: W - 2 * M, h: 0.55, rectRadius: 0.09, fill: { color: C.bg2 }, line: { color: C.orange, width: 1 } });
  s.addText("Explainable first: hand rules + SHAP + plain-English evidence.   No LLM in the runtime.", { x: M + 0.2, y: y + 0.05, w: W - 2 * M - 0.4, h: 0.55, isTextBox: true, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, color: C.ink });
  s.addNotes("Tabular ML (LightGBM), not deep learning - fast retrain, handles missing data, auditable via SHAP + rule evidence.");
}

/* ============ 17 · DASHBOARD: OVERVIEW + PRIORITY ============ */
{
  const s = slide();
  kicker(s, "The dashboard", C.blue);
  title(s, "Market overview  →  the priority list");
  shot(s, "overview.png", M, 1.95, 7.7, 4.8, "Market Overview — site map coloured by attributed cause, KPI tiles vs baseline, attribution split");
  shot(s, "priority.png", 8.65, 1.95, W - M - 8.65, 3.15);
  callout(s, 8.65, 5.3, W - M - 8.65, "Ranked top 75–100  ·  filter by cause / region", C.blue);
  callout(s, 8.65, 5.92, W - M - 8.65, "One-click export to the Phase-2 audit list (.xlsx)", C.orange);
  s.addText("Priority Sites — the ranked audit shortlist", { x: 8.65, y: 6.56, w: W - M - 8.65, h: 0.3, isTextBox: true, margin: 0, fontFace: F, fontSize: 9, italic: true, color: C.sub });
  s.addNotes("Market Overview and the ranked Priority Sites grid with the audit-list export.");
}

/* ============ 18 · DASHBOARD: SITE DETAIL ============ */
{
  const s = slide();
  kicker(s, "The dashboard", C.blue);
  title(s, "Per site — why this attribution");
  shot(s, "sitedetail.png", M, 1.95, 6.3, 4.95, "Site Detail — S00178, transport-attributed, confidence 0.98");
  const cx = 7.15, cwd = W - M - 7.15;
  [["Rule evidence", "plain-English, threshold-triggered — no model", C.orange],
   ["SHAP", "which model features drove the call", C.blue],
   ["Radio vs Transport panels", "side by side, with anomaly markers", C.mint],
   ["Ground truth (demo)", "the injected fault, so you can check it", C.purple]].forEach((it, i) => {
    const y = 2.0 + i * 1.15;
    card(s, cx, y, cwd, 0.96, { line: it[2] });
    s.addText(it[0], { x: cx + 0.22, y: y + 0.1, w: cwd - 0.44, h: 0.34, isTextBox: true, margin: 0, fontFace: F, fontSize: 11.5, bold: true, color: it[2] });
    para(s, cx + 0.22, y + 0.45, cwd - 0.44, 0.42, it[1], { size: 9.5, lsm: 1.05 });
  });
  s.addNotes("The explainability surface: rule evidence, SHAP bars, radio-vs-transport panels, and the true injected fault in demo mode.");
}

/* ============ 19 · WORKED SCENARIO ============ */
{
  const s = slide();
  kicker(s, "Worked scenario", C.orange);
  title(s, "Monday 08:10 — a monsoon fibre event", 28);
  shot(s, "incidents.png", M, 1.9, 6.7, 4.5);
  const cx = 7.55, cwd = W - M - cx;
  const steps = [
    ["Overview", "Transport-attributed count jumps overnight; an orange cluster appears in region R2 on the map."],
    ["Priority Sites", "Filter to ‘transport’ — the top rows share region R2 and an 08:00–14:00 worst window. Note S00178."],
    ["Site Detail (S00178)", "Transport panel spikes (TWAMP loss +12.7σ, SevOne queue +17.5σ); radio flat; client-RTT up, server-RTT flat; 60 % of sibling sites also degraded. Confidence 0.98."],
    ["Transport Paths", "S00178's PA-uplink shows 6.6 % loss; almost every sibling on it is orange → the fault is the link, not 19 sites."],
    ["Incidents / RCA", "Already localised: ‘shared transport fault → 1 link, explains 100 %, matched INC005’. Action: inspect the fibre span / Rx power."],
    ["Export", "Send the R2 cluster to the field team as one audit item — the link — with the recommended checks."],
  ];
  steps.forEach((st, i) => {
    const y = 1.9 + i * 0.87;
    numCircle(s, cx, y + 0.02, 0.34, i + 1, C.orange);
    s.addText(st[0], { x: cx + 0.48, y, w: cwd - 0.5, h: 0.3, isTextBox: true, margin: 0, fontFace: F, fontSize: 10.5, bold: true, color: C.ink });
    para(s, cx + 0.48, y + 0.28, cwd - 0.5, 0.58, st[1], { size: 8.3, lsm: 1.06 });
  });
  s.addNotes("A concrete investigation: a wet-weather fibre degradation hitting a regional cluster, from symptom to a single audit item in six clicks.");
}

/* ============ 20 · DEPLOY / USERS / TROUBLESHOOT ============ */
{
  const s = slide(C.bg2);
  kicker(s, "Deploy & operate", C.mint);
  title(s, "Standalone, controllable, explainable");
  const cols = [
    ["Who uses it", C.blue, ["NOC / service assurance — daily triage", "IP transport ops — target the link", "RAN optimisation — filter transport noise", "Planning — recurring congestion → upgrades", "Field audit team — the prioritised list"]],
    ["Deploy & control", C.mint, ["docker compose up  — or native (uv + Node)", "API + dashboard on :8000; SQLite only", "Windows / Linux; VS Code tasks included", "Data Generation page: presets, distributions, labelled incidents, live progress"]],
    ["Troubleshoot", C.orange, ["‘none’ = degraded, cause unclear — don't dispatch", "low confidence → corroborate on Transport Paths", "no data → run generate + analytics", "reach from a laptop → bind 0.0.0.0 + open port", "OOM → fewer sites / days"]],
  ];
  const cw = (W - 2 * M - 0.7) / 3;
  cols.forEach(([h, col, items], i) => {
    const x = M + i * (cw + 0.35);
    card(s, x, 1.95, cw, 3.5, { line: col });
    s.addText(h, { x: x + 0.22, y: 2.12, w: cw - 0.4, h: 0.4, isTextBox: true, margin: 0, fontFace: F, fontSize: 13.5, bold: true, color: col });
    bullets(s, x + 0.22, 2.62, cw - 0.44, 3.1, items, { size: 9.3, gap: 7 });
  });
  s.addText("github.com/manjunathsept11/ran-transport-isolation", { x: M, y: 6.2, w: 8, h: 0.4, isTextBox: true, margin: 0, fontFace: F, fontSize: 12, bold: true, color: C.blue });
  s.addText("Docs in the repo:  README  ·  DASHBOARD_GUIDE  ·  METHODS  ·  DATA_GENERATION  ·  INSTALL_VM", { x: M, y: 6.58, w: W - 2 * M, h: 0.35, isTextBox: true, margin: 0, fontFace: F, fontSize: 10, color: C.sub });
  s.addNotes("Packaging, personas, the control surface, and the common gotchas.");
}

P.writeFile({ fileName: "RAN_Transport_Isolation.pptx" }).then((f) => console.log("wrote", f));
