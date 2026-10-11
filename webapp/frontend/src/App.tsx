import type { ReactNode } from "react";
import { Component } from "react";
import { HashRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import AuthGate from "./components/AuthGate";
import Dashboard from "./pages/Dashboard";
import JobSearch from "./pages/JobSearch";
import Jobs from "./pages/Jobs";
import Tracker from "./pages/Tracker";
import JobDetail from "./pages/JobDetail";
import Applications from "./pages/Applications";
import ResumeTailoring from "./pages/ResumeTailoring";
import Recruiters from "./pages/Recruiters";
import Outreach from "./pages/Outreach";
import Followups from "./pages/Followups";
import Approvals from "./pages/Approvals";
import Browser from "./pages/Browser";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";
import CustomQA from "./pages/CustomQA";

class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error("Frontend route render error:", error); }
  render() {
    if (this.state.error) {
      return (
        <div className="reference-page">
          <div className="reference-panel" style={{ maxWidth: 760, margin: "48px auto" }}>
            <h1 style={{ marginTop: 0 }}>This section could not load</h1>
            <p style={{ color: "#6f6a60", lineHeight: 1.6 }}>
              A frontend error occurred while rendering this page. Reload this route after the dev server finishes rebuilding.
            </p>
            <pre style={{ whiteSpace: "pre-wrap", color: "#9b3d27", fontSize: 12, background: "#f7e7e3", padding: 12, borderRadius: 12, overflow: "auto" }}>
              {this.state.error.message}
            </pre>
            <button className="my-btn dark" onClick={() => window.location.reload()}>Reload page</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <AuthGate>
    <HashRouter>
      <Layout>
        <RouteErrorBoundary>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/job-search" element={<JobSearch />} />
            <Route path="/tracker" element={<Tracker />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/applications" element={<Applications />} />
            <Route path="/resume-tailoring" element={<ResumeTailoring />} />
            <Route path="/recruiters" element={<Recruiters />} />
            <Route path="/outreach" element={<Outreach />} />
            <Route path="/followups" element={<Followups />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/browser" element={<Browser />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/qa" element={<CustomQA />} />
          </Routes>
        </RouteErrorBoundary>
      </Layout>
    </HashRouter>
    </AuthGate>
  );
}
