import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const hub = "http://127.0.0.1:8765";
const apiPaths = ["/health", "/goals", "/projects", "/tasks", "/workspaces", "/memories"];

// `pnpm --dir apps/web build` writes dist/, which the Hub serves at `/`.
// `pnpm --dir apps/web dev` serves the UI on :5173 and proxies API calls to the Hub.
export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(apiPaths.map((p) => [p, hub])) },
  build: { outDir: "dist", emptyOutDir: true },
});
