"use client";

import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { CitationLabel } from "@/lib/api";
import { InlineCitation } from "./InlineCitation";

interface Props {
  content: string;
  sources: string[];
  labels: Array<CitationLabel | null>;
  onCitationClick?: (page: number) => void;
}

const CITATION_PATTERN = /\[p\.(\d+)\]/g;

/**
 * 답변 본문 markdown 렌더 + [p.N] 인라인 인용을 InlineCitation 으로 치환.
 *
 * 동작:
 * - react-markdown + remark-gfm 으로 마크다운 (굵게/리스트/링크) 렌더
 * - text node 를 walk 하면서 /\[p\.(\d+)\]/g 매칭 위치를 InlineCitation 으로 분할
 * - source_pages_label 의 page 와 매칭해 carousel index (1-indexed) 부여
 */
export function MarkdownAnswer({
  content,
  sources,
  labels,
  onCitationClick,
}: Props) {
  // page → carousel index (1-indexed) 맵 (labels 우선, 없으면 sources 순서)
  const pageToIndex = new Map<number, number>();
  labels.forEach((label, i) => {
    if (label?.page != null) {
      // 첫 등장만 기록 (같은 페이지 청크 여러 개일 때)
      if (!pageToIndex.has(label.page)) {
        pageToIndex.set(label.page, i + 1);
      }
    }
  });

  function renderText(text: string): ReactNode[] {
    const out: ReactNode[] = [];
    let lastIdx = 0;
    let match: RegExpExecArray | null;
    CITATION_PATTERN.lastIndex = 0;
    while ((match = CITATION_PATTERN.exec(text)) !== null) {
      if (match.index > lastIdx) {
        out.push(text.slice(lastIdx, match.index));
      }
      const page = Number(match[1]);
      const carouselIndex = pageToIndex.get(page) ?? page;
      const label = labels.find((l) => l?.page === page) ?? null;
      const preview =
        sources[carouselIndex - 1]?.replace(/\n/g, " ").slice(0, 200) ?? "";
      out.push(
        <InlineCitation
          key={`cite-${match.index}`}
          page={page}
          carouselIndex={carouselIndex}
          label={label}
          preview={preview}
          onActivate={onCitationClick}
        />,
      );
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < text.length) {
      out.push(text.slice(lastIdx));
    }
    return out;
  }

  // children(ReactNode) 안의 string을 walk 하며 인용 치환
  function transformChildren(children: ReactNode): ReactNode {
    if (typeof children === "string") {
      const parts = renderText(children);
      return <>{parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}</>;
    }
    if (Array.isArray(children)) {
      return children.map((c, i) => (
        <Fragment key={i}>{transformChildren(c)}</Fragment>
      ));
    }
    return children;
  }

  return (
    <div className="prose prose-sm max-w-none text-slate-700 leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{transformChildren(children)}</p>,
          li: ({ children }) => <li>{transformChildren(children)}</li>,
          h1: ({ children }) => <h1>{transformChildren(children)}</h1>,
          h2: ({ children }) => <h2>{transformChildren(children)}</h2>,
          h3: ({ children }) => <h3>{transformChildren(children)}</h3>,
          strong: ({ children }) => <strong>{transformChildren(children)}</strong>,
          em: ({ children }) => <em>{transformChildren(children)}</em>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
