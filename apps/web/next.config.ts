import type { NextConfig } from "next";

// A página fala com a API pela mesma origem (`/api/*`): o cookie de sessão (httpOnly, SameSite=Lax)
// e o CSRF funcionam sem CORS, e o SSE passa pelo mesmo proxy.
const API_URL = process.env.API_URL ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: false,
  async rewrites() {
    return [{ source: "/api/:caminho*", destination: `${API_URL}/:caminho*` }];
  },
};

export default nextConfig;
