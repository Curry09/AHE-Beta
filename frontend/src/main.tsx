import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";

// 左：Phaser 像素小镇（移植自 agent-town）；右：Issue + main，点小人弹完整对话。
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
