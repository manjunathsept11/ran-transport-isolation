import { useQuery } from "@tanstack/react-query";

const BASE = "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

export type Attribution = "transport" | "ran" | "shared" | "none";

export interface StatusResp {
  has_data: boolean;
  generation?: {
    run_id: string; preset: string; n_sites: number; n_links: number;
    n_incidents: number; duration_days: number; start_date: string; created_at: string;
    row_counts: Record<string, number>;
  } | null;
  analytics?: { run_id: string; created_at: string; metrics: any } | null;
}

export interface SiteRow {
  site_id: string; region: string; morphology: string; lat: number; lon: number;
  backhaul_type: string; impact_score: number; is_priority: number;
  primary_attribution: Attribution; rank: number | null;
}

export interface OverviewResp {
  sites: SiteRow[];
  trend: any[];
  kpi_now: Record<string, number>;
  kpi_baseline: Record<string, number>;
  summary: {
    n_sites: number; n_priority: number; attribution_mix: Record<string, number>;
    sessions_impacted: number; users_impacted: number;
  };
}

export interface ScorecardRow {
  site_id: string; region: string; morphology: string; rank: number; impact_score: number;
  severity_tcp_rtt: number; severity_tcp_fail: number; severity_throughput: number;
  severity_vonr: number; severity_youtube: number;
  sessions_impacted: number; users_impacted: number;
  worst_window_start: string; worst_window_end: string;
  primary_attribution: Attribution; attribution_confidence: number; is_priority: number;
  rule_evidence: string[]; ml_top_features: [string, number][];
  rule_class: Attribution; ml_class: Attribution;
}

export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: () => get<StatusResp>("/api/status"), refetchInterval: 4000 });
export const useOverview = () => useQuery({ queryKey: ["overview"], queryFn: () => get<OverviewResp>("/api/overview") });
export const useScorecard = (priority = true) =>
  useQuery({ queryKey: ["scorecard", priority], queryFn: () => get<ScorecardRow[]>(`/api/scorecard?priority_only=${priority}`) });
export const useSite = (id: string) => useQuery({ queryKey: ["site", id], queryFn: () => get<any>(`/api/sites/${id}`), enabled: !!id });
export const useLinks = () => useQuery({ queryKey: ["links"], queryFn: () => get<any[]>("/api/links") });
export const useLink = (id: string) => useQuery({ queryKey: ["link", id], queryFn: () => get<any>(`/api/links/${encodeURIComponent(id)}`), enabled: !!id });
export const useIncidents = () => useQuery({ queryKey: ["incidents"], queryFn: () => get<any>("/api/incidents") });
export const useAnomalies = () => useQuery({ queryKey: ["anomalies"], queryFn: () => get<any[]>("/api/anomalies") });
export const useVariability = () => useQuery({ queryKey: ["variability"], queryFn: () => get<any>("/api/variability") });
export const useCorrelations = () => useQuery({ queryKey: ["correlations"], queryFn: () => get<any[]>("/api/correlations") });
export const usePresets = () => useQuery({ queryKey: ["presets"], queryFn: () => get<any[]>("/api/presets") });
export const useConfig = (preset: string) => useQuery({ queryKey: ["config", preset], queryFn: () => get<any>(`/api/config/${preset}`), enabled: !!preset });
export const useJobs = () => useQuery({ queryKey: ["jobs"], queryFn: () => get<any[]>("/api/jobs"), refetchInterval: 2000 });
export const useJob = (id?: string) =>
  useQuery({ queryKey: ["job", id], queryFn: () => get<any>(`/api/jobs/${id}`), enabled: !!id, refetchInterval: 1500 });

export const startGenerate = (body: any) => post<{ job_id: string }>("/api/jobs/generate", body);
export const startAnalytics = () => post<{ job_id: string }>("/api/jobs/analytics");
export const startReport = () => post<{ job_id: string }>("/api/jobs/report?fmt=html");
export const savePreset = (name: string, config: any) => post("/api/config", { name, config });

export { get, post };
