"use client";

interface Props {
  sources: string[];
  metadata?: Record<string, unknown>;
}

export function SourceCard({ sources, metadata }: Props) {
  if (sources.length === 0) return null;

  const sourcePages = (metadata?.source_pages as (number | null)[] | undefined) ?? [];

  return (
    <details className="mt-3 rounded-md border border-slate-200 bg-white p-3 text-sm">
      <summary className="cursor-pointer font-medium text-slate-700">
        출처 ({sources.length}개 청크)
      </summary>
      <div className="mt-2 space-y-2">
        {sources.slice(0, 5).map((src, i) => {
          const page = sourcePages[i];
          const preview = src.replace(/\n/g, " ").slice(0, 240);
          return (
            <div key={i} className="border-l-2 border-slate-200 pl-2">
              <div className="text-xs text-slate-500">
                [{i + 1}] {page != null ? `p.${(page as number) + 1}` : "—"}
              </div>
              <div className="text-slate-600">
                {preview}
                {src.length > 240 ? "…" : ""}
              </div>
            </div>
          );
        })}
      </div>
    </details>
  );
}
