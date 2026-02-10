"use client";

import { useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Header from "../components/Header";

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

const KB = { primary: "#0114A7", bg: "#F7F9FD", gray050: "#EDF1F7" };

function base64UrlDecode(b64url: string) {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const txt = decodeURIComponent(escape(window.atob(b64 + pad)));
  return txt;
}

function buildRecommendationText(data: ProductResult) {
  const header = `[금융 탐정 에이전트 추천 결과]\n`;
  const meta = `${data.product_type ? `유형: ${data.product_type}\n` : ""}${data.reason ? `요약: ${data.reason}\n` : ""}`;

  const list = data.products
    .map((p, i) => {
      const rate =
        p.rate == null ? "-" : String(p.rate).includes("%") ? String(p.rate) : `${p.rate}%`;
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

export default function SharePage() {
  const sp = useSearchParams();
  const router = useRouter();
  const [toast, setToast] = useState("");

  const decoded = useMemo(() => {
    const raw = sp.get("data");
    if (!raw) return null;
    try {
      const txt = base64UrlDecode(raw);
      const obj = JSON.parse(txt);
      // { v, created_at, data } 또는 data만 들어오는 경우 둘 다 처리
      const data: ProductResult = obj?.data?.products ? obj.data : obj;
      if (!data || !Array.isArray(data.products)) return null;
      return data;
    } catch {
      return null;
    }
  }, [sp]);

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(""), 1600);
  };

  const copyText = async () => {
    if (!decoded) return;
    const text = buildRecommendationText(decoded);
    try {
      await navigator.clipboard.writeText(text);
      showToast("텍스트를 복사했어요");
    } catch {
      showToast("복사 실패");
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      showToast("링크를 복사했어요");
    } catch {
      showToast("복사 실패");
    }
  };

  return (
    <main className="min-h-screen" style={{ background: KB.bg, color: "#1F2937" }}>
      <Header title="추천 결과 공유" />

      <div className="max-w-5xl mx-auto w-full px-4 py-6">
        {!decoded ? (
          <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-6">
            <div className="text-lg font-bold text-gray-900">유효하지 않은 링크예요</div>
            <div className="mt-2 text-sm text-gray-600">
              공유 링크가 잘못되었거나 만료/손상되었을 수 있어요.
            </div>
            <button
              type="button"
              onClick={() => router.push("/chat")}
              className="mt-4 h-10 px-4 rounded-xl text-sm font-semibold"
              style={{ background: KB.primary, color: "white" }}
            >
              챗으로 가기
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-bold" style={{ color: KB.primary }}>
                    {decoded.product_type ?? "추천 결과"}
                  </div>
                  {decoded.reason ? (
                    <div className="mt-1 text-sm text-gray-700">{decoded.reason}</div>
                  ) : null}
                </div>

                <div className="flex gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={copyText}
                    className="h-9 px-4 rounded-xl text-sm font-semibold border border-gray-200 bg-white"
                    style={{ color: KB.primary }}
                  >
                    📋 텍스트 복사
                  </button>
                  <button
                    type="button"
                    onClick={copyLink}
                    className="h-9 px-4 rounded-xl text-sm font-semibold"
                    style={{ background: KB.primary, color: "white" }}
                  >
                    🔗 링크 복사
                  </button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {decoded.products.map((p, idx) => {
                const rate =
                  p.rate == null ? "" : String(p.rate).includes("%") ? String(p.rate) : `${p.rate}%`;
                const cond = p.special_condition_summary ?? p.special_condition_raw ?? "";
                return (
                  <div key={idx} className="bg-white border border-gray-100 rounded-2xl shadow-sm p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-xs text-gray-500">{p.bank ?? "금융사"}</div>
                      {rate ? (
                        <div className="text-sm font-extrabold" style={{ color: KB.primary }}>
                          {rate}
                        </div>
                      ) : null}
                    </div>

                    <div className="mt-1 text-[15px] font-semibold text-gray-900 line-clamp-2">
                      {p.name ?? "상품명"}
                    </div>

                    {p.why_recommended ? (
                      <div className="mt-2 text-sm text-gray-600 whitespace-pre-line line-clamp-4">
                        {p.why_recommended}
                      </div>
                    ) : null}

                    {cond ? (
                      <div className="mt-3 rounded-xl bg-[#F7F9FD] p-3 text-xs text-gray-700 whitespace-pre-line line-clamp-4">
                        <span className="font-semibold" style={{ color: KB.primary }}>
                          우대
                        </span>{" "}
                        {cond}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>

            {decoded.notes ? (
              <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-5">
                <div className="text-xs font-bold text-gray-900">메모</div>
                <div className="mt-2 text-sm text-gray-700 whitespace-pre-line">{decoded.notes}</div>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {toast && (
        <div className="fixed left-1/2 -translate-x-1/2 bottom-24 z-[60]">
          <div className="px-4 py-2 rounded-full bg-black/80 text-white text-sm shadow-lg">
            {toast}
          </div>
        </div>
      )}
    </main>
  );
}
