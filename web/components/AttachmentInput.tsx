"use client";

import { useRef, useState } from "react";
import { Paperclip, X } from "lucide-react";
import type { Attachment } from "@/lib/api";
import { resizeImage } from "@/lib/imageResize";

interface Props {
  attachments: Attachment[];
  onChange: (next: Attachment[]) => void;
  disabled?: boolean;
  /** 리사이즈 후 단일 이미지 최대 크기 (bytes). 기본 2MB. */
  maxBytes?: number;
  /** 리사이즈 전 원본 최대 크기 (bytes). 너무 큰 파일은 처음부터 거부. */
  maxOriginalBytes?: number;
}

const DEFAULT_MAX = 2 * 1024 * 1024;
// 원본은 최대 25MB 까지 허용 — Canvas 가 들어 올릴 수 있는 한계 근처
const DEFAULT_MAX_ORIGINAL = 25 * 1024 * 1024;

/**
 * 입력창 옆 paperclip 버튼 — 이미지 첨부 (base64 data URL).
 * 첨부된 이미지는 작은 thumb + 삭제 버튼으로 표시.
 */
export function AttachmentInput({
  attachments,
  onChange,
  disabled,
  maxBytes = DEFAULT_MAX,
  maxOriginalBytes = DEFAULT_MAX_ORIGINAL,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setBusy(true);
    const next: Attachment[] = [...attachments];
    try {
      for (const file of Array.from(files)) {
        if (!file.type.startsWith("image/")) {
          setError(`${file.name}: 이미지 파일만 가능`);
          continue;
        }
        if (file.size > maxOriginalBytes) {
          setError(
            `${file.name}: ${(file.size / 1024 / 1024).toFixed(1)}MB — ` +
              `${(maxOriginalBytes / 1024 / 1024).toFixed(0)}MB 이하만 (원본)`,
          );
          continue;
        }
        try {
          // 자동 리사이즈 — 1024px / JPEG 85%, 한도 초과 시 768px / 70% 재시도
          const result = await resizeImage(file, { maxBytes });
          if (result.approxBytes > maxBytes) {
            setError(
              `${file.name}: 축소 후에도 ${(result.approxBytes / 1024 / 1024).toFixed(1)}MB — 더 작은 이미지 필요`,
            );
            continue;
          }
          next.push({ type: "image", data_url: result.dataUrl, name: file.name });
        } catch {
          setError(`${file.name}: 이미지 처리 실패`);
        }
      }
      onChange(next);
    } finally {
      setBusy(false);
    }
  }

  function removeAt(idx: number) {
    onChange(attachments.filter((_, i) => i !== idx));
  }

  return (
    <div className="flex flex-col gap-1">
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {attachments.map((a, i) => (
            <div
              key={i}
              className="relative w-16 h-16 rounded border border-slate-200 overflow-hidden bg-slate-50"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={a.data_url}
                alt={a.name ?? `attachment-${i}`}
                className="w-full h-full object-cover"
              />
              <button
                type="button"
                onClick={() => removeAt(i)}
                disabled={disabled}
                className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-slate-700 text-white flex items-center justify-center hover:bg-rose-500 disabled:opacity-50"
                aria-label="첨부 제거"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      {error && (
        <p className="text-[11px] text-rose-600">{error}</p>
      )}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || busy}
        title={busy ? "이미지 처리 중…" : "이미지 첨부 (자동 축소)"}
        aria-label="이미지 첨부"
        className="self-start p-1.5 text-slate-500 hover:text-primary disabled:opacity-50"
      >
        <Paperclip size={16} className={busy ? "animate-pulse" : ""} />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          handleFiles(e.target.files);
          // 같은 파일 재선택 가능하도록 reset
          if (inputRef.current) inputRef.current.value = "";
        }}
      />
    </div>
  );
}
