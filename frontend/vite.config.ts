import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The API address for dev and preview. Override with BACKEND_URL when :8000 is taken.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
const proxy = { "/api": { target: backend, changeOrigin: true } };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
});
