import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import "./index.css";
import Overview from "./pages/Overview";
import Sessions from "./pages/Sessions";
import SessionDetail from "./pages/SessionDetail";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <nav>
        <Link to="/">概览</Link>
        <Link to="/sessions">会话</Link>
      </nav>
      <div className="container">{children}</div>
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
        </Routes>
      </Shell>
    </BrowserRouter>
  </React.StrictMode>
);
