import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on port 8000; the Vite dev server proxies /api there so
// the frontend and backend stay in sync without CORS fiddling in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
