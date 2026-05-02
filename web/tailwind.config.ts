import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 차분한 신학 도메인 톤 — 사용자 선호 ("차분한 시니어 개발자 톤")
        primary: { DEFAULT: "#1e40af", light: "#3b82f6" },
        ink: "#1f2937",
      },
      fontFamily: {
        // 한국어 본문 가독성
        sans: ["system-ui", "-apple-system", "Pretendard", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
