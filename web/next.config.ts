import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev badge sits over the sidebar user card.
  devIndicators: false,
  // The browser tests run their own `next dev` (port 3010) next to yours: a separate build folder keeps the two apart.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
};

export default nextConfig;
