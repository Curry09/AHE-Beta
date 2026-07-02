import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import Office from "./office/Office";

// 单屏公司办公室看板：详情走内部抽屉状态（奥卡姆剃刀，无 react-router）。
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Office />
  </React.StrictMode>
);
