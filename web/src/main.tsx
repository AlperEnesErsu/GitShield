import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { ReposPage } from "./pages/ReposPage";
import { RepoPage } from "./pages/RepoPage";
import { PullPage } from "./pages/PullPage";
import { InboxPage } from "./pages/InboxPage";
import { TriagePage } from "./pages/TriagePage";
import { MetricsPage } from "./pages/MetricsPage";
import { AchievementsPage } from "./pages/AchievementsPage";
import { NotFoundPage } from "./components/ErrorBoundary";
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
