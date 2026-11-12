import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Em dev a API roda no host (make api, porta 8000); em produção o nginx faz o mesmo proxy.
const api = process.env.VITE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/v1": api, "/health": api } },
  preview: { proxy: { "/v1": api, "/health": api } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
