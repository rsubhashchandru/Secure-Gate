/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow long-running requests (OCR on scanned PDFs can take minutes)
  serverExternalPackages: [],
  experimental: {
    proxyTimeout: 300000, // 5 minutes
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
