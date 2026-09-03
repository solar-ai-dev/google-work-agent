import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        headers: { origin: apiTarget }
      },
      "/health": {
        target: apiTarget,
        changeOrigin: true,
        headers: { origin: apiTarget }
      }
    }
  },
  test: {
    include: ["tests/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"]
    }
  }
});
