import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Calvin RAG Chatbot",
  description: "칼빈 강요 RAG 챗봇 — Hybrid / Agentic / Knowledge Graph 3 모드",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
