import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import Town from "./town/Town";

// 单屏 AI 小镇：不再需要多页路由，详情走内部抽屉状态（奥卡姆剃刀，去掉 react-router）。
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Town />
  </React.StrictMode>
);
