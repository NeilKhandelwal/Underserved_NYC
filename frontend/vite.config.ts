import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy API + tile requests to the FastAPI backend so the frontend can
// use same-origin paths (/api, /tiles) in both dev and production.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/tiles": { target: API_TARGET, changeOrigin: true },
      "/healthz": { target: API_TARGET, changeOrigin: true },
    },
  },
});
