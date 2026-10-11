import type { ReactNode, ComponentType } from "react";
import logoUrl from "../assets/myjobb-logo.svg";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Search,
  Briefcase,
  ClipboardList,
  KanbanSquare,
  FileText,
  Users,
  Send,
  Mail,
  CheckCircle2,
  Globe,
  ScrollText,
  MessageSquare,
  Settings2,
  ChevronRight,
  PanelLeft,
  UserRound,
} from "lucide-react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../api/client";

type Item = {
  to: string;
  label: string;
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
  end?: boolean;
};
type NavGroup = { label: string; items: Item[] };

// Keep every functional section from the Career Agent sidebar reachable.
// The MyJobb redesign changes presentation, not product capabilities.
const NAV_GROUPS: NavGroup[] = [
  {
    label: "WORKSPACE",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/job-search", label: "Job Search", icon: Search },
      { to: "/jobs", label: "Jobs", icon: Briefcase },
      { to: "/applications", label: "Applications", icon: ClipboardList },
      { to: "/tracker", label: "Tracker", icon: KanbanSquare },
    ],
  },
  {
    label: "APPLICATION WORKFLOW",
    items: [
      { to: "/resume-tailoring", label: "Resume Tailoring", icon: FileText },
      { to: "/approvals", label: "Approvals", icon: CheckCircle2 },
    ],
  },
  {
    label: "RECRUITER OUTREACH",
    items: [
      { to: "/recruiters", label: "Recruiters", icon: Users },
      { to: "/outreach", label: "Outreach", icon: Send },
      { to: "/followups", label: "Follow-ups", icon: Mail },
    ],
  },
  {
    label: "TOOLS & CONFIGURATION",
    items: [
      { to: "/browser", label: "Browser / CDP", icon: Globe },
      { to: "/logs", label: "Logs / Audit", icon: ScrollText },
      { to: "/qa", label: "Custom Q&A", icon: MessageSquare },
      { to: "/settings", label: "Settings", icon: Settings2 },
    ],
  },
];

function LinkItem({ item }: { item: Item }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={item.label}
      className={({ isActive }) => `mj-side-link ${isActive ? "active" : ""}`}
    >
      <Icon size={16} strokeWidth={1.8} />
      <span>{item.label}</span>
    </NavLink>
  );
}

const ROUTE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/job-search": "Job Search",
  "/jobs": "Jobs for you",
  "/applications": "Applications",
  "/tracker": "Tracker",
  "/resume-tailoring": "Resume Tailoring",
  "/recruiters": "Recruiters",
  "/outreach": "Outreach",
  "/followups": "Follow-ups",
  "/approvals": "Approvals",
  "/browser": "Browser / CDP",
  "/logs": "Logs / Audit",
  "/qa": "Custom Q&A",
  "/settings": "Settings",
};

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { data: cfg } = usePolling(() => api.config(), 60000);
  const path = location.pathname;
  const inJobDetail = path.startsWith("/jobs/");
  const title = inJobDetail ? "Job details" : (ROUTE_TITLES[path] ?? "Career Agent");
  const candidate = cfg?.candidate_id || "Anuroop Varma";

  return (
    <div className="mj-shell">
      <aside className="mj-sidebar-real">
        <NavLink to="/" className="mj-logo-real" aria-label="MyJobb dashboard">
          <img src={logoUrl} alt="myjobb" />
        </NavLink>
        <nav className="mj-nav-real" aria-label="Main navigation">
          {NAV_GROUPS.map((group) => (
            <section className="mj-nav-group" key={group.label} aria-label={group.label}>
              <div className="mj-nav-section-title">{group.label}</div>
              {group.items.map((item) => <LinkItem key={item.to} item={item} />)}
            </section>
          ))}
        </nav>
        <div className="mj-user-real" title={candidate}>
          <div className="mj-user-avatar-real"><UserRound size={17} /></div>
          <span>{candidate}</span>
        </div>
      </aside>

      <div className="mj-main-real">
        <header className="mj-header-real">
          <div className="mj-breadcrumb">
            <button aria-label="Navigation" title="Navigation"><PanelLeft size={21} /></button>
            {inJobDetail && <><NavLink className="crumb-muted" to="/jobs">Jobs for you</NavLink><ChevronRight size={15} /></>}
            <strong>{title}</strong>
          </div>
        </header>
        <main className="mj-main-scroll">{children}</main>
      </div>
    </div>
  );
}
