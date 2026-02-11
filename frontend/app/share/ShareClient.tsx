"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";

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

function base64UrlDecode(b64url: string) {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  return decodeURIComponent(escape(window.atob(b64 + pad)));
}

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

export default function ShareClient() {
  const sp = useSearchParams();
  const encoded = sp.get("data") ?? "";

  const parsed = useMemo(() => {
    if (!encoded) return { ok: false as const, error: "공유 데이터가 없어요." };

    // 1) decode
    const decodedText = (() => {
      try {
        return base64UrlDecode(encoded);
      } catch {
        return null;
      }
    })();
    if (!decodedText) return { ok: false as const, error: "링크 데이터 디코딩에 실패했어요." };

    // 2) parse JSON
    const json = safeJsonParse<any>(decodedText);
    if (!json) return { ok: false as const, error: "링크 데이터가 JSON 형식이 아니에요." };

    // 3) payload 형태(v, created_at, data) / 혹은 data가 바로 ProductResult인 경우 둘 다 허용
    const data = json?.data ?? json;
    if (!isProductResult(data)) return { ok: false as const, error: "유효하지 않은 추천 데이터예요." };

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
          <div className="mt-4 text-xs text-gray-400 break-all">
            data={encoded || "(empty)"}
          </div>
        </div>
      </div>
    );
  }

  const data = parsed.data;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
      <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm text-gray-700">
              <span className="font-extrabold" style={{ color: KB.primary }}>
                {data.product_type ?? "추천 결과"}
              </span>
              {data.reason ? <span className="ml-2">{data.reason}</span> : null}
            </div>
            {parsed.created_at ? (
              <div className="mt-1 text-xs text-gray-400">
                생성: {new Date(parsed.created_at).toLocaleString("ko-KR")}
              </div>
            ) : null}
          </div>

          <button
            type="button"
            className="h-9 px-4 rounded-full text-sm font-semibold"
            style={{ background: KB.primary, color: "white" }}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(window.location.href);
                alert("현재 링크를 복사했어요");
              } catch {
                alert("복사 실패 (브라우저 권한 확인)");
              }
            }}
          >
            🔗 링크 복사
          </button>
        </div>

        {data.notes ? (
          <div className="mt-4 text-sm text-gray-600 whitespace-pre-wrap">{data.notes}</div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pb-10">
        {data.products.map((p, idx) => (
          <div
            key={idx}
            className="bg-white border border-gray-100 rounded-2xl shadow-sm p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs text-gray-500 truncate">{p.bank ?? "금융사"}</div>
                <div className="mt-1 text-[15px] font-semibold text-gray-900 leading-snug">
                  {p.name ?? "상품명"}
                </div>
              </div>

              {p.rate ? (
                <div
                  className="shrink-0 px-3 py-1 rounded-full text-sm font-extrabold"
                  style={{ background: "rgba(1,20,167,0.08)", color: KB.primary }}
                >
                  {fmtRate(p.rate)}
                </div>
              ) : null}
            </div>

            {p.why_recommended ? (
              <div className="mt-3 text-sm text-gray-700 whitespace-pre-line">
                {p.why_recommended}
              </div>
            ) : null}

            {(p.special_condition_summary || p.special_condition_raw) ? (
              <div className="mt-3 rounded-xl bg-[#F7F9FD] p-3 text-xs text-gray-700 whitespace-pre-line">
                <span className="font-semibold" style={{ color: KB.primary }}>
                  우대조건
                </span>{" "}
                {p.special_condition_summary ?? p.special_condition_raw}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
