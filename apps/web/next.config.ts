import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@resident-os/shared-types", "@resident-os/ui"],
};

export default nextConfig;
