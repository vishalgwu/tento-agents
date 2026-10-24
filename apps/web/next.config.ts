import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@resident-os/shared-types"],
};

export default nextConfig;
