/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // Proxy the API in development so the browser sees one origin and CORS
    // never enters the picture.
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.SIGMA_API_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
