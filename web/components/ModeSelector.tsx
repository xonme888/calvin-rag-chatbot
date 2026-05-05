"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import type { Mode, ModeInfo } from "@/lib/api";

interface Props {
  modes: ModeInfo[];
  current: Mode;
  onChange: (mode: Mode) => void;
}

const AUTO_INFO: ModeInfo = {
  name: "auto",
  label: "자동",
  available: true,
  reason: null,
};

/**
 * 모드 선택 — 디폴트는 "자동" (백엔드 라우터가 결정).
 * 고급 옵션 토글로 펼치면 Hybrid/Agentic/KG 강제 선택 가능.
 *
 * 의도: 사용자에게 RAG 모드 (구현 디테일) 를 노출하지 않는다. 시연/디버깅
 * 목적으로 강제 모드 선택은 고급 옵션 안에 숨겨둔다.
 */
export function ModeSelector({ modes, current, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const isAuto = current === "auto";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange("auto")}
          title="질문에 따라 적합한 모드를 자동 선택"
          className={[
            "px-3 py-1.5 rounded-md text-sm border transition-colors flex items-center gap-1.5",
            isAuto
              ? "bg-primary text-white border-primary"
              : "bg-white text-ink border-slate-300 hover:bg-slate-100",
          ].join(" ")}
        >
          <Sparkles size={13} />
          자동
        </button>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="text-[11px] text-slate-500 hover:text-slate-700 flex items-center gap-0.5"
          aria-expanded={open}
        >
          고급
          {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
        {!isAuto && (
          <span className="text-[11px] text-slate-500">
            현재 강제 선택:{" "}
            {modes.find((m) => m.name === current)?.label ?? current}
          </span>
        )}
      </div>

      {open && (
        <div className="flex gap-1.5 flex-wrap mt-1 pl-1">
          {/* 비활성 모드는 목록에서 아예 숨김 — 사용자에게 인프라 디테일 노출 X */}
          {[AUTO_INFO, ...modes.filter((m) => m.available)].map((m) => {
            const active = current === m.name;
            return (
              <button
                key={m.name}
                type="button"
                onClick={() => onChange(m.name)}
                title={m.label}
                className={[
                  "px-2 py-1 rounded text-[12px] border transition-colors cursor-pointer",
                  active
                    ? "bg-primary text-white border-primary"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50",
                ].join(" ")}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
