import type { NextConfig } from "next";

// A dev server must not share output files with `next build`. Concurrent
// writes into `.next` can leave manifests referencing chunks that were removed
// by the other command (for example, `Cannot find module './976.js'`).
const nextConfig: NextConfig = {
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
};

export default nextConfig;
