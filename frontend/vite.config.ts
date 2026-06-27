import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev 时把 /api 代理到 uvicorn（默认 8000），生产由 FastAPI 托管 dist。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
