import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// Production: a static export (out/) that the FastAPI backend serves together with /api on one origin
// (ui/server/main.py; the password gate lives there too). Development: `next dev` forwards /api/* to the backend.
const backend = (process.env.API_PROXY_TARGET || "http://127.0.0.1:8787").replace(/\/$/, "");

export default function config(phase: string): NextConfig {
  const base: NextConfig = {
    cacheComponents: false,
    images: { unoptimized: true },
    turbopack: {
      rules: {
        "*.css": {
          loaders: ["@tailwindcss/turbopack"],
          as: "*.css",
        },
      },
    },
  };
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return { ...base, async rewrites() { return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]; } };
  }
  return { ...base, output: "export" };
}
