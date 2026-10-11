import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // next dev would otherwise write AGENTS.md/CLAUDE.md into this service dir.
  agentRules: false,
  // The dev "N" badge covered the mobile tab bar at 390px (UX audit, shell).
  devIndicators: false,
};

export default nextConfig;
