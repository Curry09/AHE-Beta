import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";

// dev 时把 /api 代理到 uvicorn（默认 8000），生产由 FastAPI 托管 dist。
export default defineConfig({
  plugins: [react()],
  resolve: {
    // 与移植自 agent-town 的引擎保持 `@/` 绝对导入（指向 src）。
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
