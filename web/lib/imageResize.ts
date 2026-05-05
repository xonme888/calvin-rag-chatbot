/**
 * 클라이언트 측 이미지 리사이즈 — Canvas API.
 *
 * 목적: 사용자 원본 (수십 MB) 을 backend/vision 한도 안으로 자동 축소.
 * 백엔드 vision 은 detail="low" (65토큰 고정) 라 큰 해상도가 무의미 —
 * 1024px / JPEG 85% 면 인식 충분 + 용량 ~수백 KB.
 *
 * 사용:
 *   const dataUrl = await resizeImage(file);
 */

const DEFAULT_MAX_DIM = 1024;
const DEFAULT_QUALITY = 0.85;

interface ResizeOptions {
  /** 긴 변 픽셀 한도. 기본 1024. */
  maxDim?: number;
  /** JPEG 품질 (0~1). 기본 0.85. */
  quality?: number;
  /** 결과 data URL 의 byte 한도. 초과 시 quality 낮춰 재시도. */
  maxBytes?: number;
}

interface ResizeResult {
  dataUrl: string;
  width: number;
  height: number;
  approxBytes: number;
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("이미지 로드 실패"));
    img.src = src;
  });
}

function computeFit(
  w: number,
  h: number,
  maxDim: number,
): { width: number; height: number } {
  if (w <= maxDim && h <= maxDim) return { width: w, height: h };
  const ratio = w > h ? maxDim / w : maxDim / h;
  return { width: Math.round(w * ratio), height: Math.round(h * ratio) };
}

function approxBytesOfDataUrl(dataUrl: string): number {
  // "data:image/jpeg;base64," 접두사 제외 + base64 inflation 4/3 보정
  const commaIdx = dataUrl.indexOf(",");
  const body = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl;
  return Math.floor((body.length * 3) / 4);
}

/**
 * 이미지를 한도 내로 축소해 data URL 로 반환.
 * 첫 시도가 한도 초과 시 maxDim 768 / quality 0.7 로 재시도.
 */
export async function resizeImage(
  file: File,
  options: ResizeOptions = {},
): Promise<ResizeResult> {
  const maxDim = options.maxDim ?? DEFAULT_MAX_DIM;
  const quality = options.quality ?? DEFAULT_QUALITY;
  const maxBytes = options.maxBytes;

  const original = await fileToDataUrl(file);
  const img = await loadImage(original);
  const fit = computeFit(img.naturalWidth, img.naturalHeight, maxDim);

  let dataUrl = await renderToDataUrl(img, fit.width, fit.height, quality);
  let approxBytes = approxBytesOfDataUrl(dataUrl);

  // 한도 초과 시 한 번 더 (작은 maxDim + 낮은 quality)
  if (maxBytes != null && approxBytes > maxBytes) {
    const fit2 = computeFit(img.naturalWidth, img.naturalHeight, 768);
    dataUrl = await renderToDataUrl(img, fit2.width, fit2.height, 0.7);
    approxBytes = approxBytesOfDataUrl(dataUrl);
    return { dataUrl, width: fit2.width, height: fit2.height, approxBytes };
  }

  return { dataUrl, width: fit.width, height: fit.height, approxBytes };
}

async function renderToDataUrl(
  img: HTMLImageElement,
  width: number,
  height: number,
  quality: number,
): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context 생성 실패");
  ctx.drawImage(img, 0, 0, width, height);
  // alpha 채널이 없는 일반 사진엔 JPEG 가 PNG 보다 훨씬 작음
  return canvas.toDataURL("image/jpeg", quality);
}
