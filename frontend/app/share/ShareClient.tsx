"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { decompressFromEncodedURIComponent } from "lz-string";

const KB = {
  primary: "#0114A7",
  bg: "#F7F9FD",
  gray050: "#EDF1F7",
};

type ProductResult = {
  product_type?: string;
  reason?: string;
  products: Array<{
    bank?: string;
    name?: string;
    rate?: string | number;
    special_condition_summary?: string;
    special_condition_raw?: string;
    why_recommended?: string;
  }>;
  notes?: string;
};

function safeJsonParse<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

function isProductResult(x: any): x is ProductResult {
  return x && typeof x === "object" && Array.isArray(x.products);
}

function fmtRate(rate: string | number | undefined) {
  if (rate == null) return "";
  const s = String(rate);
  return s.includes("%") ? s : `${s}%`;
}

function buildRecommendationText(data: ProductResult, createdAt?: string | null) {
  const header = `[금융 탐정 에이전트 추천 결과]\n`;
  const meta = `${data.product_type ? `유형: ${data.product_type}\n` : ""}${
    data.reason ? `요약: ${data.reason}\n` : ""
  }${createdAt ? `생성: ${new Date(createdAt).toLocaleString("ko-KR")}\n` : ""}`;

  const list = data.products
    .map((p, i) => {
      const rate =
        p.rate == null
          ? "-"
          : String(p.rate).includes("%")
          ? String(p.rate)
          : `${p.rate}%`;
      const cond = p.special_condition_summary ?? p.special_condition_raw ?? "-";
      const why = p.why_recommended ?? "-";
      const title = `${i + 1}. ${(p.bank ?? "").trim()} ${p.name ?? ""}`.trim();

      return `${title}
- 금리: ${rate}
- 추천 이유: ${why}
- 우대조건: ${cond}
`;
    })
    .join("\n");

  const notes = data.notes ? `\n[메모]\n${data.notes}\n` : "";
  return `${header}${meta}\n${list}${notes}`.trim();
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

function ActionButton({
  icon,
  label,
  onClick,
  primary,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "h-9 px-3 rounded-full text-[13px] font-semibold",
        "inline-flex items-center gap-2",
        "transition active:scale-[0.98] shadow-sm",
        primary ? "" : "border border-gray-200 bg-white",
      ].join(" ")}
      style={primary ? { background: KB.primary, color: "white" } : { color: KB.primary }}
    >
      {icon}
      <span className="whitespace-nowrap">{label}</span>
    </button>
  );
}

export default function ShareClient() {
  const sp = useSearchParams();
  const encoded = sp.get("data") ?? "";
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 1500);
  };

  const parsed = useMemo(() => {
    if (!encoded) return { ok: false as const, error: "공유 데이터가 없어요." };

    const decodedText = (() => {
      try {
        return decompressFromEncodedURIComponent(encoded);
      } catch {
        return null;
      }
    })();

    if (!decodedText) return { ok: false as const, error: "링크 데이터 복원 실패" };

    const json = safeJsonParse<any>(decodedText);
    if (!json) return { ok: false as const, error: "JSON 파싱 실패" };

    const data = json?.data ?? json;
    if (!isProductResult(data))
      return { ok: false as const, error: "유효하지 않은 추천 데이터" };

    return {
      ok: true as const,
      created_at: typeof json?.created_at === "string" ? json.created_at : null,
      data,
    };
  }, [encoded]);

  if (!parsed.ok) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-10">
        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="text-sm font-semibold text-gray-900">유효하지 않은 링크</div>
          <div className="mt-2 text-sm text-gray-600">{parsed.error}</div>
        </div>
      </div>
    );
  }

  const data = parsed.data;

  const handleCopyLink = async () => {
    const url = `${window.location.origin}/share?data=${encoded}`;
    const ok = await copyToClipboard(url);
    showToast(ok ? "링크를 복사했어요" : "복사 실패");
  };

  const handleCopyText = async () => {
    const text = buildRecommendationText(data, parsed.created_at);
    const ok = await copyToClipboard(text);
    showToast(ok ? "추천 결과를 복사했어요" : "복사 실패");
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
      {/* 상단 요약 카드 */}
      <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-5">
        {/* ✅ 모바일: 세로 / 데스크탑: 가로 */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="min-w-0">
            <div className="text-sm text-gray-700">
              <span className="font-extrabold" style={{ color: KB.primary }}>
                {data.product_type ?? "추천 결과"}
              </span>
              {data.reason ? <span className="ml-2">{data.reason}</span> : null}
            </div>

            {parsed.created_at && (
              <div className="mt-1 text-xs text-gray-400">
                생성: {new Date(parsed.created_at).toLocaleString("ko-KR")}
              </div>
            )}

            <div className="mt-3 text-sm text-gray-600">
              원하면 조건(급여이체/카드실적/신규 등)을 더 확인해서 추천을 더 좁힐 수 있어요.
            </div>
          </div>

          {/* 버튼 영역 */}
          <div className="flex gap-2 justify-end sm:justify-start">
            <ActionButton
              primary
              label="링크 복사"
              onClick={handleCopyLink}
              icon={
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M10 13a5 5 0 0 1 0-7l1-1a5 5 0 0 1 7 7l-1 1"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                  <path
                    d="M14 11a5 5 0 0 1 0 7l-1 1a5 5 0 0 1-7-7l1-1"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                </svg>
              }
            />

            <ActionButton
              label="텍스트 복사"
              onClick={handleCopyText}
              icon={
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M8 7h10M8 11h10M8 15h7"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                  <rect
                    x="4"
                    y="4"
                    width="16"
                    height="16"
                    rx="2"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                </svg>
              }
            />
          </div>
        </div>
      </div>

      {/* 상품 리스트 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pb-10">
        {data.products.map((p, idx) => (
          <div
            key={idx}
            className="bg-white border border-gray-100 rounded-2xl shadow-sm p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs text-gray-500 truncate">
                  {p.bank ?? "금융사"}
                </div>
                <div className="mt-1 text-[15px] font-semibold text-gray-900">
                  {p.name ?? "상품명"}
                </div>
              </div>

              {p.rate && (
                <div
                  className="shrink-0 px-3 py-1 rounded-full text-sm font-extrabold"
                  style={{
                    background: "rgba(1,20,167,0.08)",
                    color: KB.primary,
                  }}
                >
                  {fmtRate(p.rate)}
                </div>
              )}
            </div>

            {p.why_recommended && (
              <div className="mt-3 text-sm text-gray-700 whitespace-pre-line">
                {p.why_recommended}
              </div>
            )}

            {(p.special_condition_summary || p.special_condition_raw) && (
              <div className="mt-3 rounded-xl bg-[#F7F9FD] p-3 text-xs text-gray-700 whitespace-pre-line">
                <span className="font-semibold" style={{ color: KB.primary }}>
                  우대조건
                </span>{" "}
                {p.special_condition_summary ?? p.special_condition_raw}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 토스트 */}
      {toast && (
        <div className="fixed left-1/2 -translate-x-1/2 bottom-24 z-[60]">
          <div className="px-4 py-2 rounded-full bg-black/80 text-white text-sm shadow-lg">
            {toast}
          </div>
        </div>
      )}
    </div>
  );
}
