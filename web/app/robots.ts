import type { MetadataRoute } from "next";

/**
 * 검색엔진 노출 차단 — 포트폴리오/초대 코드 운영 단계.
 *
 * Robots.txt:
 * User-agent: *
 * Disallow: /
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        disallow: "/",
      },
    ],
  };
}
