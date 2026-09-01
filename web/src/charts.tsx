import ReactECharts from "echarts-for-react";
import { C } from "./theme";

// echarts-for-react sizes to its container on mount; in a flex/grid card the width can
// still be 0 at that instant, leaving an empty canvas. Nudge a resize once painted.
const ready = (chart: any) => {
  requestAnimationFrame(() => chart?.resize?.());
  setTimeout(() => chart?.resize?.(), 60);
};

const base = {
  backgroundColor: "transparent",
  textStyle: { color: C.muted, fontFamily: "Inter, sans-serif" },
  grid: { left: 46, right: 16, top: 28, bottom: 30, containLabel: true },
  tooltip: { trigger: "axis", backgroundColor: "#1c2637", borderColor: C.line, textStyle: { color: C.ink } },
};

const axis = {
  axisLine: { lineStyle: { color: C.line } },
  splitLine: { lineStyle: { color: "#1e283c" } },
  axisLabel: { color: C.muted, fontSize: 11 },
};

export function TimeSeries({ data, series, height = 240, markLines }: {
  data: any[];
  series: { key: string; name: string; color?: string; yAxis?: number }[];
  height?: number;
  markLines?: { xAxis: string; label?: string; color?: string }[];
}) {
  const x = data.map((d) => d.ts_hour || d.ts);
  const multiY = series.some((s) => s.yAxis === 1);
  const option = {
    ...base,
    legend: { top: 0, textStyle: { color: C.muted }, itemWidth: 10, itemHeight: 10 },
    xAxis: { type: "category", data: x, ...axis, boundaryGap: false },
    yAxis: multiY
      ? [{ type: "value", ...axis }, { type: "value", ...axis, splitLine: { show: false } }]
      : { type: "value", ...axis },
    series: series.map((s, i) => ({
      name: s.name,
      type: "line",
      showSymbol: false,
      smooth: true,
      yAxisIndex: s.yAxis || 0,
      lineStyle: { width: 1.6, color: s.color || C.grid[i % C.grid.length] },
      itemStyle: { color: s.color || C.grid[i % C.grid.length] },
      data: data.map((d) => d[s.key]),
      markLine: i === 0 && markLines?.length
        ? {
            symbol: "none",
            data: markLines.map((m) => ({
              xAxis: m.xAxis,
              lineStyle: { color: m.color || C.warn, type: "dashed" },
              label: { show: !!m.label, formatter: m.label, color: C.muted, fontSize: 10 },
            })),
          }
        : undefined,
    })),
  };
  return <ReactECharts option={option} style={{ height, width: "100%" }} notMerge onChartReady={ready} />;
}

export function BarChart({ items, height = 240, horizontal = false, colorBy }: {
  items: { name: string; value: number; color?: string }[];
  height?: number; horizontal?: boolean; colorBy?: boolean;
}) {
  const cat = { type: "category", data: items.map((i) => i.name), ...axis };
  const val = { type: "value", ...axis };
  const option = {
    ...base,
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? cat : val,
    series: [{
      type: "bar",
      data: items.map((i, k) => ({
        value: i.value,
        itemStyle: { color: i.color || (colorBy ? C.grid[k % C.grid.length] : C.accent), borderRadius: 3 },
      })),
      barMaxWidth: 26,
    }],
  };
  return <ReactECharts option={option} style={{ height, width: "100%" }} notMerge onChartReady={ready} />;
}

export function Heatmap({ x, y, data, height = 320, min = 0, max = 5 }: {
  x: string[]; y: string[]; data: [number, number, number][]; height?: number; min?: number; max?: number;
}) {
  const option = {
    ...base,
    grid: { left: 60, right: 20, top: 10, bottom: 60, containLabel: true },
    tooltip: { position: "top", backgroundColor: "#1c2637", borderColor: C.line, textStyle: { color: C.ink } },
    xAxis: { type: "category", data: x, ...axis, axisLabel: { color: C.muted, fontSize: 9, rotate: 45 } },
    yAxis: { type: "category", data: y, ...axis, axisLabel: { color: C.muted, fontSize: 10 } },
    visualMap: {
      min, max, calculable: true, orient: "horizontal", left: "center", bottom: 0,
      textStyle: { color: C.muted },
      inRange: { color: ["#16203100", "#e7b53f", "#f0763c", "#e35d6a"] },
    },
    series: [{ type: "heatmap", data, emphasis: { itemStyle: { borderColor: C.ink, borderWidth: 1 } } }],
  };
  return <ReactECharts option={option} style={{ height, width: "100%" }} notMerge onChartReady={ready} />;
}

export function GeoScatter({ points, height = 380, onClick }: {
  points: { lon: number; lat: number; color: string; r: number; id: string }[];
  height?: number;
  onClick?: (id: string) => void;
}) {
  if (!points.length) return <div className="grid place-items-center text-muted text-sm" style={{ height }}>no sites</div>;
  const lons = points.map((p) => p.lon), lats = points.map((p) => p.lat);
  const pad = 0.03;
  const x0 = Math.min(...lons) - pad, x1 = Math.max(...lons) + pad;
  const y0 = Math.min(...lats) - pad, y1 = Math.max(...lats) + pad;
  const W = 1000, H = Math.round((W * (y1 - y0)) / (x1 - x0) || W * 0.66);
  const sx = (lon: number) => ((lon - x0) / (x1 - x0)) * W;
  const sy = (lat: number) => H - ((lat - y0) / (y1 - y0)) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ height, width: "100%" }}
      className="rounded-lg" preserveAspectRatio="xMidYMid meet">
      <rect x={0} y={0} width={W} height={H} fill="#0b101a" />
      {Array.from({ length: 6 }).map((_, i) => (
        <line key={i} x1={0} x2={W} y1={(H / 6) * i} y2={(H / 6) * i} stroke="#18202f" strokeWidth={1} />
      ))}
      {[...points].sort((a, b) => a.r - b.r).map((p) => (
        <circle key={p.id} cx={sx(p.lon)} cy={sy(p.lat)} r={p.r * 1.4}
          fill={p.color} fillOpacity={0.85} stroke="#0b101a" strokeWidth={0.8}
          style={{ cursor: onClick ? "pointer" : "default" }}
          onClick={() => onClick?.(p.id)}>
          <title>{p.id}</title>
        </circle>
      ))}
    </svg>
  );
}

export function MiniSpark({ data, color = C.accent, height = 34 }: { data: number[]; color?: string; height?: number }) {
  const option = {
    backgroundColor: "transparent",
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: "category", show: false, data: data.map((_, i) => i), boundaryGap: false },
    yAxis: { type: "value", show: false, scale: true },
    series: [{ type: "line", data, showSymbol: false, smooth: true, lineStyle: { width: 1.3, color },
              areaStyle: { color: color + "22" } }],
  };
  return <ReactECharts option={option} style={{ height, width: 90 }} notMerge />;
}
