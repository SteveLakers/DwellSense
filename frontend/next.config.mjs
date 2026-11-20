/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["mapbox-gl"],
  async redirects() {
    return [
      {
        // Old project URL; preview deployments use other *.vercel.app hosts and are unaffected.
        source: "/:path*",
        has: [{ type: "host", value: "dwellsense.vercel.app" }],
        destination: "https://zermap.com/:path*",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
