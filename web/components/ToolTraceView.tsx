"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";

export interface ToolCall {
  tool: string;
  args?: Record<string, unknown>;
  // 향후 output_preview 추가 가능 (현재 백엔드는 tool/args 만 노출)
}

interface Props {
  calls: ToolCall[];
}

/**
 * Agentic 모드 답변의 도구 호출 단계를 접힘 형태로 노출.
 * 답변 본문 위에 작게 표시 — 사용자가 펼치면 각 호출의 tool/args.
 */
export function ToolTraceView({ calls }: Props) {
  const [open, setOpen] = useState(false);
  if (calls.length === 0) return null;

  return (
    <div className="mb-3 rounded-md border border-slate-200 bg-slate-50/60 text-[12px]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-1.5 px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-t-md"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Wrench size={12} className="text-slate-500" />
        <span>도구 사용 — {calls.length}회</span>
      </button>
      {open && (
        <ol className="border-t border-slate-200 px-3 py-2 space-y-2">
          {calls.map((c, i) => (
            <li key={i} className="text-slate-700">
              <div className="flex items-baseline gap-2">
                <span className="text-[10px] font-mono text-slate-400">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="font-mono font-medium text-primary">
                  {c.tool}
                </span>
              </div>
              {c.args && Object.keys(c.args).length > 0 && (
                <pre className="mt-1 ml-6 text-[11px] font-mono text-slate-500 whitespace-pre-wrap break-words bg-white border border-slate-200 rounded p-1.5">
                  {JSON.stringify(c.args, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
