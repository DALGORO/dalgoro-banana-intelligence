// frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

const apiProxy = {
  "/api": {
    target: "http://127.0.0.1:8000",
    changeOrigin: true,
  },
};

const localAccessHosts = ["localhost", "127.0.0.1", ".trycloudflare.com"];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    allowedHosts: localAccessHosts,
    proxy: apiProxy,
  },
  // El Control Center ejecuta `vite preview`; por eso el proxy /api y los
  // hosts de Quick Tunnel deben estar habilitados también en preview.
  preview: {
    port: 4173,
    allowedHosts: localAccessHosts,
    proxy: apiProxy,
  },
});
