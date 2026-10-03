import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // next dev would otherwise write AGENTS.md/CLAUDE.md into this service dir.
  agentRules: false,
};

export default nextConfig;
