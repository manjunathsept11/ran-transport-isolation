import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import {
  Activity, AlertTriangle, GitBranch, LayoutDashboard, ListChecks, Radio,
  Settings as SettingsIcon, Waves,
} from "lucide-react";
import clsx from "clsx";
import { useStatus } from "./api";
import Overview from "./pages/Overview";
import PrioritySites from "./pages/PrioritySites";
import SiteDetail from "./pages/SiteDetail";
import Transport from "./pages/Transport";
import Incidents from "./pages/Incidents";
import Anomalies from "./pages/Anomalies";
import Variability from "./pages/Variability";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Market Overview", icon: LayoutDashboard, end: true },
  { to: "/priority", label: "Priority Sites", icon: ListChecks },
  { to: "/transport", label: "Transport Paths", icon: GitBranch },
  { to: "/incidents", label: "Incidents / RCA", icon: AlertTriangle },
  { to: "/anomalies", label: "Anomaly Explorer", icon: Activity },
  { to: "/variability", label: "Variability", icon: Waves },
  { to: "/settings", label: "Data Generation", icon: SettingsIcon },
];

function Sidebar() {
  const { data: status } = useStatus();
  return (
    <aside className="w-60 shrink-0 border-r border-line bg-panel flex flex-col">
      <div className="px-4 py-4 border-b border-line flex items-center gap-2">
        <Radio className="text-accent" size={20} />
        <div>
          <div className="font-semibold text-sm leading-tight">RAN / Transport</div>
          <div className="text-[11px] text-muted">Isolation Module</div>
        </div>
      </div>
      <nav className="flex-1 p-2 space-y-0.5">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              clsx("flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition",
                isActive ? "bg-accent/15 text-accent" : "text-muted hover:text-ink hover:bg-panel2")
            }
          >
            <n.icon size={16} /> {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-line text-[11px] text-muted space-y-0.5">
        {status?.has_data && status.generation ? (
          <>
            <div>preset <span className="text-ink">{status.generation.preset}</span></div>
            <div>{status.generation.n_sites} sites · {status.generation.duration_days}d · {status.generation.n_incidents} incidents</div>
            {status.analytics ? (
              <div className="text-good">analytics ready</div>
            ) : (
              <div className="text-warn">run analytics</div>
            )}
          </>
        ) : (
          <div className="text-warn">no dataset — go to Data Generation</div>
        )}
      </div>
    </aside>
  );
}

function NoData() {
  const nav = useNavigate();
  return (
    <div className="flex-1 grid place-items-center">
      <div className="card p-8 text-center max-w-sm">
        <AlertTriangle className="mx-auto text-warn mb-3" />
        <div className="font-medium mb-1">No dataset loaded</div>
        <p className="text-sm text-muted mb-4">
          Generate a synthetic dataset to populate the dashboard.
        </p>
        <button className="btn btn-primary mx-auto" onClick={() => nav("/settings")}>
          Go to Data Generation
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const { data: status, isLoading } = useStatus();
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <div className="max-w-[1500px] mx-auto p-6">
          {isLoading ? null : (
            <Routes>
              <Route path="/settings" element={<Settings />} />
              {status?.has_data ? (
                <>
                  <Route path="/" element={<Overview />} />
                  <Route path="/priority" element={<PrioritySites />} />
                  <Route path="/sites/:id" element={<SiteDetail />} />
                  <Route path="/transport" element={<Transport />} />
                  <Route path="/incidents" element={<Incidents />} />
                  <Route path="/anomalies" element={<Anomalies />} />
                  <Route path="/variability" element={<Variability />} />
                </>
              ) : (
                <Route path="*" element={<NoData />} />
              )}
            </Routes>
          )}
        </div>
      </main>
    </div>
  );
}
