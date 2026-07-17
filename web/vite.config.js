import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI backend (uvicorn on :8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
    // The Python sources are imported ?raw from ../catan_review (single
    // source of truth for the in-browser engine).
    fs: { allow: [".."] },
  },
});
