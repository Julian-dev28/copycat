import type { NextConfig } from "next";
import base from "./next.config.base";
const config: NextConfig = { ...base, turbopack: { ...(base.turbopack ?? {}), root: "/Users/julian_dev/Documents/code/copycat" }, outputFileTracingRoot: "/Users/julian_dev/Documents/code/copycat" };
export default config;
