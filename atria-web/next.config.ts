import type { NextConfig } from "next";

/**
 * Where the engine lives.
 *
 * Read at build time by Next, so it must be set before the first build on
 * Vercel. Locally it defaults to the address `make demo` listens on.
 */
const ENGINE = process.env.NEXT_PUBLIC_ATRIA_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /*
   * Proxy the API through this app rather than calling the engine from the
   * browser.
   *
   * The browser then only ever talks to its own origin, so CORS never enters
   * into it and the engine does not need to know the front end's URL. That
   * matters more than it sounds: the allow-list on the engine is a real
   * control — it refuses cross-origin writes from anywhere unnamed — and
   * widening it for every preview deployment Vercel generates would hollow it
   * out. This way it stays narrow and the front end still works.
   *
   * The websocket is deliberately NOT proxied. Vercel's routing layer does not
   * carry websocket upgrades, and it does not need to: websockets are not
   * subject to CORS, so the browser can open one straight to the engine from
   * any origin. Verified against the deployed service before relying on it.
   */
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${ENGINE}/v1/:path*` },
      { source: "/api/:path*", destination: `${ENGINE}/api/:path*` },
    ];
  },
};

export default nextConfig;
