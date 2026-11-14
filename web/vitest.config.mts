import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths()],
  esbuild: { jsx: "automatic" },
  css: { postcss: { plugins: [] } },
  test: { environment: "jsdom", include: ["tests/**/*.test.{ts,tsx}"], globals: false, setupFiles: ["tests/setup.ts"] },
});
