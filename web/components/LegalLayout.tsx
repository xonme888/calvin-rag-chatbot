import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  updatedAt: string; // YYYY-MM-DD
  children: ReactNode;
}

/**
 * 약관/방침/저작권 정적 페이지 공통 레이아웃.
 * 메인 챗 화면과 분리된 단순 본문 — 사이드바/입력창 없음.
 */
export function LegalLayout({ title, updatedAt, children }: Props) {
  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            href="/"
            className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-slate-700"
            aria-label="홈으로"
          >
            <ArrowLeft size={18} />
          </Link>
          <h1 className="text-base font-semibold">{title}</h1>
          <span className="ml-auto text-[11px] text-slate-400">
            최종 갱신 {updatedAt}
          </span>
        </div>
      </header>
      <article className="max-w-2xl mx-auto px-4 py-8 prose prose-sm prose-slate">
        {children}
      </article>
      <footer className="border-t border-slate-200 bg-white py-4">
        <nav className="max-w-2xl mx-auto px-4 flex gap-4 text-[11px] text-slate-500">
          <Link href="/terms" className="hover:text-primary">서비스 약관</Link>
          <Link href="/privacy" className="hover:text-primary">개인정보 처리방침</Link>
          <Link href="/license" className="hover:text-primary">데이터 출처 / 저작권</Link>
        </nav>
      </footer>
    </main>
  );
}
