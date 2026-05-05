"use client";

import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { CitationLabel, MatchedTerm } from "@/lib/api";
import { InlineCitation } from "./InlineCitation";
import { TermTooltip } from "./TermTooltip";

interface Props {
  content: string;
  sources: string[];
  labels: Array<CitationLabel | null>;
  onCitationClick?: (page: number) => void;
  /** 답변 안 글로서리 매칭 — inline tooltip 용. 없으면 인용만 처리. */
  matchedTerms?: MatchedTerm[];
}

const CITATION_PATTERN = /\[p\.(\d+)\]/g;

function escapeRegex(s: string): string {
  return s.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
}

/**
 * 답변 본문 markdown 렌더 + [p.N] 인라인 인용 + 글로서리 용어 tooltip 치환.
 *
 * 동작:
 * - react-markdown + remark-gfm 으로 마크다운 렌더
 * - text node 를 walk 하면서 인용 + 글로서리 alias 모두 한 정규식으로 매칭
 *   (긴 alias 우선 → 짧은 substring 누락 방지)
 * - 인용은 InlineCitation, 용어는 TermTooltip 으로 치환
 */
export function MarkdownAnswer({
  content,
  sources,
  labels,
  onCitationClick,
  matchedTerms,
}: Props) {
  // page → carousel index (1-indexed) 맵 (labels 우선, 없으면 sources 순서)
  const pageToIndex = new Map<number, number>();
  labels.forEach((label, i) => {
    if (label?.page != null && !pageToIndex.has(label.page)) {
      pageToIndex.set(label.page, i + 1);
    }
  });

  // alias → MatchedTerm 룩업 + 동적 정규식 (긴 단어 우선)
  const aliasMap = new Map<string, MatchedTerm>();
  for (const t of matchedTerms ?? []) {
    aliasMap.set(t.term, t);
    for (const a of t.aliases) aliasMap.set(a, t);
  }
  const aliasList = Array.from(aliasMap.keys()).sort(
    (a, b) => b.length - a.length,
  );
  const combinedPattern = aliasList.length
    ? new RegExp(
        `\\[p\\.(\\d+)\\]|(${aliasList.map(escapeRegex).join("|")})`,
        "g",
      )
    : CITATION_PATTERN;

  function renderText(text: string): ReactNode[] {
    const out: ReactNode[] = [];
    let lastIdx = 0;
    let match: RegExpExecArray | null;
    combinedPattern.lastIndex = 0;
    while ((match = combinedPattern.exec(text)) !== null) {
      if (match.index > lastIdx) {
        out.push(text.slice(lastIdx, match.index));
      }
      // 인용 매칭 (group 1) 우선
      if (match[1] !== undefined) {
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
      } else if (match[2] !== undefined) {
        // 글로서리 alias 매칭
        const alias = match[2];
        const term = aliasMap.get(alias);
        if (term) {
          out.push(
            <TermTooltip
              key={`term-${match.index}`}
              term={term}
              display={alias}
            />,
          );
        } else {
          out.push(alias);
        }
      }
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < text.length) {
      out.push(text.slice(lastIdx));
    }
    return out;
  }

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
