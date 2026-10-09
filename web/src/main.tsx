import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { ReposPage } from "./pages/ReposPage";
import { RepoPage } from "./pages/RepoPage";
import { PullPage } from "./pages/PullPage";
import "@fontsource-variable/inter";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<ReposPage />} />
          <Route path="r/:owner/:repo" element={<RepoPage />} />
          <Route path="r/:owner/:repo/pull/:number" element={<PullPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
