import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tauriConf from "./src-tauri/tauri.conf.json";

export default defineConfig({
  define: {
    // release.yml patches src-tauri/tauri.conf.json's version at release
    // time but never package.json's — read from tauri.conf.json so the
    // in-app About dialog shows the real version, not always "0.1.0" (#171).
    __APP_VERSION__: JSON.stringify(tauriConf.version),
  },
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"],
  },
});
