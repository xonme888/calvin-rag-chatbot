"use client";

import type { Mode, ModeInfo } from "@/lib/api";

interface Props {
  modes: ModeInfo[];
  current: Mode;
  onChange: (mode: Mode) => void;
}

export function ModeSelector({ modes, current, onChange }: Props) {
  return (
    <div className="flex gap-2 flex-wrap">
      {modes.map((m) => {
        const disabled = !m.available;
        const active = current === m.name && !disabled;
        return (
          <button
            key={m.name}
            type="button"
            disabled={disabled}
            onClick={() => onChange(m.name)}
            title={disabled ? m.reason ?? "비활성화" : m.label}
            className={[
              "px-3 py-1.5 rounded-md text-sm border transition-colors",
              active
                ? "bg-primary text-white border-primary"
                : "bg-white text-ink border-slate-300 hover:bg-slate-100",
              disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
            ].join(" ")}
          >
            {m.label}
            {disabled ? " (비활성)" : ""}
          </button>
        );
      })}
    </div>
  );
}
