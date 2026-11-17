import React, { lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { ReposPage } from "./pages/ReposPage";
import { RepoPage } from "./pages/RepoPage";
import { NotFoundPage } from "./components/ErrorBoundary";

// The overview and repo pages are the entry points and stay in the main bundle; the rest
// load on first visit.
const PullPage = lazy(() => import("./pages/PullPage").then((m) => ({ default: m.PullPage })));
const InboxPage = lazy(() => import("./pages/InboxPage").then((m) => ({ default: m.InboxPage })));
const TriagePage = lazy(() => import("./pages/TriagePage").then((m) => ({ default: m.TriagePage })));
const MetricsPage = lazy(() => import("./pages/MetricsPage").then((m) => ({ default: m.MetricsPage })));
const AchievementsPage = lazy(() =>
  import("./pages/AchievementsPage").then((m) => ({ default: m.AchievementsPage })));
import "@fontsource-variable/inter";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<ReposPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="triage" element={<TriagePage />} />
          <Route path="metrics" element={<MetricsPage />} />
          <Route path="achievements" element={<AchievementsPage />} />
          <Route path="r/:owner/:repo" element={<RepoPage />} />
          <Route path="r/:owner/:repo/pull/:number" element={<PullPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
