import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Hide the floating dev-tools badge. The errors it reported came from a browser
  // extension injecting bis_skin_checked/bis_register attributes into the DOM before
  // React hydrated, not from this app, so the badge was pure noise over the UI.
  // Compile and runtime errors still surface in the terminal and browser console.
  devIndicators: false,
};

export default nextConfig;
