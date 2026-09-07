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

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  // El Control Center ejecuta `vite preview`; por eso el proxy /api debe
  // existir también en preview para que laptop/iPad usen un único origen HTTPS.
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
});
