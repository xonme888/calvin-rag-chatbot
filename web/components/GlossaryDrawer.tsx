"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, Search, X } from "lucide-react";
import {
  fetchGlossary,
  fetchTermGraph,
  type MatchedTerm,
  type TermGraphResponse,
} from "@/lib/api";
import { SubgraphView, type SubgraphData } from "./SubgraphView";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * 글로서리 사이드 drawer — 좌측 검색 가능한 60개 리스트, 우측 detail.
 *
 * Detail 구성:
 * - 정의 + alias + sources (JSON, 즉시)
 * - KG 1-hop subgraph (Neo4j, 비활성 시 안내)
 *
 * 향후 옵션 D 마이그레이션:
 * - JSON 자체가 KG 의 derived view 가 되어도 본 컴포넌트는 무수정
 * - 좌측 리스트는 GET /glossary, 우측 그래프는 GET /glossary/{term}/graph 그대로
 */
export function GlossaryDrawer({ open, onClose }: Props) {
  const [terms, setTerms] = useState<MatchedTerm[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<MatchedTerm | null>(null);
  const [graph, setGraph] = useState<TermGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // 첫 open 시 글로서리 로드
  useEffect(() => {
    if (open && terms.length === 0) {
      fetchGlossary().then(setTerms);
    }
  }, [open, terms.length]);

  // selected 변경 시 KG subgraph 로드
  useEffect(() => {
    if (!selected) {
      setGraph(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchTermGraph(selected.term)
      .then((g) => {
        if (!cancelled) setGraph(g);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  // ESC 닫기
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return terms;
    return terms.filter(
      (t) =>
        t.term.toLowerCase().includes(q) ||
        t.aliases.some((a) => a.toLowerCase().includes(q)) ||
        t.definition.toLowerCase().includes(q),
    );
  }, [terms, search]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40">
      <div
        className="absolute inset-0 bg-slate-900/30"
        onClick={onClose}
        aria-hidden
      />
      <aside
        className="absolute right-0 top-0 h-full w-full max-w-3xl bg-white shadow-xl border-l border-slate-200 flex flex-col"
        role="dialog"
        aria-label="용어집"
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <BookOpen size={16} className="text-primary" />
            <h2 className="text-sm font-semibold text-ink">용어집</h2>
            <span className="text-[11px] text-slate-400">
              {terms.length}개
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100"
            aria-label="닫기"
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 flex overflow-hidden">
          {/* 좌측 — 검색 + 리스트 */}
          <div className="w-72 shrink-0 border-r border-slate-200 flex flex-col bg-slate-50/50">
            <div className="p-2 border-b border-slate-200">
              <div className="relative">
                <Search
                  size={14}
                  className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400"
                />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="용어 검색…"
                  className="w-full pl-7 pr-2 py-1.5 text-sm rounded-md border border-slate-200 bg-white focus:outline-none focus:border-primary"
                />
              </div>
            </div>
            <ul className="flex-1 overflow-y-auto py-1">
              {filtered.length === 0 && (
                <li className="px-3 py-2 text-xs text-slate-400">
                  검색 결과 없음
                </li>
              )}
              {filtered.map((t) => {
                const active = selected?.term === t.term;
                return (
                  <li key={t.term}>
                    <button
                      type="button"
                      onClick={() => setSelected(t)}
                      className={[
                        "w-full text-left px-3 py-2 text-sm transition-colors",
                        active
                          ? "bg-white border-l-2 border-primary text-ink"
                          : "border-l-2 border-transparent text-slate-700 hover:bg-white",
                      ].join(" ")}
                    >
                      <div className="font-medium">{t.term}</div>
                      {t.aliases.length > 0 && (
                        <div className="text-[10px] text-slate-400 truncate">
                          {t.aliases.slice(0, 2).join(", ")}
                        </div>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* 우측 — detail */}
          <div className="flex-1 overflow-y-auto">
            {selected ? (
              <article className="px-5 py-4">
                <header className="mb-3">
                  <h3 className="text-base font-semibold text-ink">
                    {selected.term}
                  </h3>
                  {selected.aliases.length > 0 && (
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      {selected.aliases.join(" · ")}
                    </div>
                  )}
                </header>

                <p className="text-sm text-slate-700 leading-relaxed mb-3">
                  {selected.definition}
                </p>

                {selected.sources.length > 0 && (
                  <div className="text-[11px] text-slate-500 mb-4 pb-3 border-b border-slate-100">
                    출처: {selected.sources.map((s) => s.label).join(" · ")}
                  </div>
                )}

                {/* KG 1-hop subgraph */}
                <section>
                  <h4 className="text-[11px] font-semibold text-slate-500 mb-2 uppercase tracking-wide">
                    관련 개념 그래프
                  </h4>
                  {loading && (
                    <div className="text-xs text-slate-400 py-3">
                      관계 정보 로딩 중…
                    </div>
                  )}
                  {!loading && graph && !graph.kg_available && (
                    <div className="text-xs text-slate-400 py-3">
                      관계 정보 준비 중 (KG 비활성).
                    </div>
                  )}
                  {!loading &&
                    graph?.kg_available &&
                    graph.nodes.length === 0 && (
                      <div className="text-xs text-slate-400 py-3">
                        이 용어의 관계 정보가 없습니다.
                      </div>
                    )}
                  {!loading &&
                    graph?.kg_available &&
                    graph.nodes.length > 0 && (
                      <SubgraphView
                        subgraph={graph as SubgraphData}
                        height={320}
                      />
                    )}
                </section>
              </article>
            ) : (
              <div className="px-5 py-8 text-sm text-slate-400">
                좌측 목록에서 용어를 선택하세요.
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
