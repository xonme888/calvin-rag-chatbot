/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 운영 단계에서 Cloudflare Access (Step 5) 헤더 통과 위해 필요 시 추가
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // 클라이언트 캐싱 — SSE 응답은 No-Cache 필요 (FastAPI 헤더 우선이나 안전망)
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
        ],
      },
    ];
  },
};

export default nextConfig;
