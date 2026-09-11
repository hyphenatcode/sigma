/** @type {import('next').NextConfig} */

// `rewrites()` is evaluated at BUILD time and baked into the routing table, so
// SIGMA_API_URL has to be present as a build environment variable — not just
// at runtime. Get that wrong on Vercel and the deployed site proxies /api/* to
// http://localhost:8000 for every visitor: no build error, no runtime error,
// just a site where nothing works. Fail the build instead.
// Trailing slashes are stripped because the destination below is built by
// concatenation: a dashboard value pasted as "https://host/" would otherwise
// proxy every request to "https://host//api/...", which is a path no route
// matches. Hosting dashboards copy URLs with the slash attached, so this is
// the normal way to get it wrong, not an exotic one.
const apiUrl = (process.env.SIGMA_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);
const isLocal = apiUrl.includes("localhost") || apiUrl.includes("127.0.0.1");

// VERCEL is set on every Vercel build; VERCEL_ENV is "production" | "preview"
// | "development". Preview builds against a local URL are equally broken, so
// this guards both.
if (process.env.VERCEL && isLocal) {
  throw new Error(
    "SIGMA_API_URL is unset (or points at localhost) in a Vercel build.\n" +
      "The API proxy is compiled into the build, so the deployed site would\n" +
      "send every /api/* request to localhost and fail for all visitors.\n" +
      "Set SIGMA_API_URL to the public backend URL in the Vercel project's\n" +
      "environment variables, then redeploy.",
  );
}

const nextConfig = {
  async rewrites() {
    // Proxying keeps the browser on one origin, so CORS never enters the
    // picture — in development and in production alike.
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
