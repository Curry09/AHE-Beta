import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import "./index.css";
import Overview from "./pages/Overview";
import Sessions from "./pages/Sessions";
import SessionDetail from "./pages/SessionDetail";
import Issues from "./pages/Issues";
import { AgentsPanel } from "./components/AgentsPanel";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <nav>
        <Link to="/">概览</Link>
        <Link to="/sessions">会话</Link>
        <Link to="/issues">Gitea 看板</Link>
      </nav>
      <div className="container">
        <AgentsPanel />
        {children}
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/sessions/:id" element={<SessionDetail />} />
          <Route path="/issues" element={<Issues />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  </React.StrictMode>
);
