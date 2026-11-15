import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: "localhost",
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: "chrome120",
    sourcemap: true,
  },
});
