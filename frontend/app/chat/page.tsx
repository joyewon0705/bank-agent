"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Header from "../components/Header";

type YesNoUnknown = "yes" | "no" | "unknown";

type SlotState = {
  slots: {
    monthly_amount?: number;
    term_months?: number;
    lump_sum?: number;
    income_monthly?: number;
    desired_amount?: number;
  };
  eligibility: {
    salary_transfer: YesNoUnknown;
    auto_transfer: YesNoUnknown;
    card_spend: YesNoUnknown;
    primary_bank: YesNoUnknown;
    non_face: YesNoUnknown;
    youth: YesNoUnknown;
    marketing?: YesNoUnknown;
  };
  meta: { user_uncertain: boolean };
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

type ChatMessage = { role: "user" | "assistant"; content: string };

const KB = {
  primary: "#0114A7",
  secondary: "#4262FF",
  bg: "#F7F9FD",
  gray050: "#EDF1F7",
};

function safeJsonParse<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

function isSlotState(x: any): x is SlotState {
  return (
    x &&
    typeof x === "object" &&
    x.slots &&
    x.eligibility &&
    x.meta &&
    typeof x.meta.user_uncertain === "boolean"
  );
}
function isProductResult(x: any): x is ProductResult {
  return x && typeof x === "object" && Array.isArray(x.products);
}

function splitTextAndJsonBlocks(
  content?: string
): Array<{ kind: "text" | "json"; value: string }> {
  if (typeof content !== "string") return [];
  const trimmed = content.trim();

  const whole = safeJsonParse<any>(trimmed);
  if (whole && typeof whole === "object") return [{ kind: "json", value: trimmed }];

  const blocks: Array<{ kind: "text" | "json"; value: string }> = [];
  const regex = /```json\s*([\s\S]*?)\s*```/gi;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    const before = content.slice(lastIndex, match.index);
    if (before.trim().length) blocks.push({ kind: "text", value: before });
    blocks.push({ kind: "json", value: match[1] });
    lastIndex = regex.lastIndex;
  }

  const after = content.slice(lastIndex);
  if (after.trim().length) blocks.push({ kind: "text", value: after });

  return blocks.length ? blocks : [{ kind: "text", value: content }];
}

function LoadingBubble() {
  return (
    <div className="flex justify-start">
      <div className="bg-white border border-gray-100 p-4 rounded-[22px] rounded-tl-none shadow-sm">
        <div className="flex space-x-1">
          <div className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" />
          <div className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.15s]" />
          <div className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.3s]" />
        </div>
      </div>
    </div>
  );
}

function SlotCarousel({ state }: { state: SlotState }) {
  const fmtWon = (n?: number) => (n == null ? "-" : `${n.toLocaleString("ko-KR")}원`);
  const fmtMonths = (n?: number) => (n == null ? "-" : `${n}개월`);

  const cards = [
    {
      title: "금액/기간",
      rows: [
        ["월 납입", fmtWon(state.slots.monthly_amount)],
        ["목돈", fmtWon(state.slots.lump_sum)],
        ["기간", fmtMonths(state.slots.term_months)],
      ],
    },
    {
      title: "대출",
      rows: [
        ["월 소득", fmtWon(state.slots.income_monthly)],
        ["희망 금액", fmtWon(state.slots.desired_amount)],
      ],
    },
    {
      title: "조건",
      rows: [
        ["급여이체", state.eligibility.salary_transfer],
        ["자동이체", state.eligibility.auto_transfer],
        ["카드실적", state.eligibility.card_spend],
        ["주거래", state.eligibility.primary_bank],
        ["비대면", state.eligibility.non_face],
        ["청년", state.eligibility.youth],
      ],
    },
    { title: "메타", rows: [["확신 낮음", state.meta.user_uncertain ? "true" : "false"]] },
  ];

  return (
    <div className="space-y-2">
      <div className="text-sm text-gray-600">
        <span className="font-semibold" style={{ color: KB.primary }}>
          추출된 정보
        </span>
      </div>

      <div className="flex gap-3 overflow-x-auto pr-2 snap-x snap-mandatory [-webkit-overflow-scrolling:touch]">
        {cards.map((c, idx) => (
          <div
            key={idx}
            className="snap-start min-w-[260px] max-w-[260px] bg-white border border-gray-100 rounded-2xl shadow-sm p-4"
          >
            <div className="flex items-center justify-between">
              <div className="text-[15px] font-semibold text-gray-900">{c.title}</div>
              <div className="w-2 h-2 rounded-full" style={{ background: KB.secondary }} />
            </div>

            <div className="mt-3 space-y-2">
              {c.rows.map(([k, v], i) => (
                <div key={i} className="flex items-center justify-between gap-3">
                  <div className="text-xs text-gray-500">{k}</div>
                  <div className="text-sm font-semibold text-gray-900 truncate">{v}</div>
                </div>
              ))}
            </div>

            <button
              type="button"
              className="mt-3 w-full h-10 rounded-xl text-sm font-semibold"
              style={{ background: KB.gray050, color: KB.primary }}
            >
              수정/추가하기
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** ✅ 추천 상품 "자세히 보기" 바텀시트/모달 */
function ProductDetailSheet({
  open,
  product,
  onClose,
}: {
  open: boolean;
  product: ProductResult["products"][number] | null;
  onClose: () => void;
}) {
  if (!open || !product) return null;

  const bank = product.bank ?? "금융사";
  const name = product.name ?? "상품명";
  const rate =
    product.rate == null
      ? ""
      : String(product.rate).includes("%")
      ? String(product.rate)
      : `${product.rate}%`;
  const cond = product.special_condition_raw ?? product.special_condition_summary ?? "";
  const why = product.why_recommended ?? "";

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose} aria-hidden="true" />

      <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6">
        <div
          className="w-full sm:max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl shadow-xl max-h-[86vh] overflow-hidden"
          role="dialog"
          aria-modal="true"
        >
          {/* header */}
          <div className="px-5 pt-5 pb-4 border-b border-gray-100">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs text-gray-500 truncate">{bank}</div>
                <div className="mt-1 text-base font-extrabold text-gray-900 leading-snug">
                  {name}
                </div>
              </div>

              <button
                type="button"
                onClick={onClose}
                className="shrink-0 h-9 w-9 rounded-full border border-gray-200 flex items-center justify-center"
                aria-label="닫기"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M6 6l12 12M18 6L6 18"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>

            {rate ? (
              <div className="mt-3">
                <span
                  className="inline-flex px-3 py-1 rounded-full text-sm font-extrabold"
                  style={{ background: "rgba(1,20,167,0.12)", color: KB.primary }}
                >
                  {rate}
                </span>
              </div>
            ) : null}
          </div>

          {/* body */}
          <div className="px-5 py-4 overflow-y-auto max-h-[calc(86vh-140px)] space-y-4">
            {why ? (
              <div className="rounded-2xl border border-gray-100 p-4">
                <div className="text-xs font-bold text-gray-900">추천 이유</div>
                <div className="mt-2 text-sm text-gray-700 whitespace-pre-line leading-relaxed">
                  {why}
                </div>
              </div>
            ) : null}

            <div className="rounded-2xl bg-[#F7F9FD] p-4">
              <div className="text-xs font-bold" style={{ color: KB.primary }}>
                우대조건 / 특약
              </div>
              <div className="mt-2 text-sm text-gray-800 whitespace-pre-line leading-relaxed">
                {cond ? cond : "제공 정보 없음"}
              </div>
            </div>
          </div>

          {/* footer */}
          <div className="px-5 py-4 border-t border-gray-100 bg-white">
            <button
              type="button"
              onClick={onClose}
              className="h-11 w-full rounded-xl text-sm font-semibold"
              style={{ background: KB.primary, color: "white" }}
            >
              닫기
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function ProductCarousel({ data }: { data: ProductResult }) {
  const fmtRate = (rate: string | number | undefined) => {
    if (rate == null) return "";
    const s = String(rate);
    return s.includes("%") ? s : `${s}%`;
  };

  // ✅ detail state
  const [detailOpen, setDetailOpen] = useState(false);
  const [selected, setSelected] = useState<ProductResult["products"][number] | null>(null);

  const openDetail = (p: ProductResult["products"][number]) => {
    setSelected(p);
    setDetailOpen(true);
  };
  const closeDetail = () => {
    setDetailOpen(false);
    setSelected(null);
  };

  return (
    <div className="space-y-3">
      {(data.product_type || data.reason) && (
        <div className="text-sm text-gray-600">
          <span className="font-semibold" style={{ color: KB.primary }}>
            {data.product_type ?? "추천"}
          </span>
          {data.reason ? <span className="ml-2">{data.reason}</span> : null}
        </div>
      )}

      <div className="flex gap-3 overflow-x-auto pr-2 snap-x snap-mandatory [-webkit-overflow-scrolling:touch]">
        {data.products.map((p, idx) => (
          <div
            key={idx}
            className="snap-start min-w-[280px] max-w-[280px] bg-white border border-gray-100 rounded-2xl shadow-sm p-4"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="text-xs text-gray-500">{p.bank ?? "금융사"}</div>
              {p.rate ? (
                <div className="text-sm font-bold" style={{ color: KB.primary }}>
                  {fmtRate(p.rate)}
                </div>
              ) : null}
            </div>

            <div className="mt-1 text-[15px] font-semibold text-gray-900 line-clamp-2">
              {p.name ?? "상품명"}
            </div>

            {p.why_recommended && (
              <div className="mt-2 text-sm text-gray-600 line-clamp-3">{p.why_recommended}</div>
            )}

            {(p.special_condition_summary || p.special_condition_raw) && (
              <div className="mt-3 rounded-xl bg-[#F7F9FD] p-3 text-xs text-gray-600 line-clamp-4">
                <span className="font-semibold" style={{ color: KB.primary }}>
                  우대
                </span>{" "}
                {p.special_condition_summary ?? p.special_condition_raw}
              </div>
            )}

            <button
              type="button"
              onClick={() => openDetail(p)}
              className="mt-3 w-full h-10 rounded-xl text-sm font-semibold"
              style={{ background: KB.gray050, color: KB.primary }}
            >
              자세히 보기
            </button>
          </div>
        ))}
      </div>

      {data.notes && <div className="text-xs text-gray-500 whitespace-pre-wrap">{data.notes}</div>}

      {/* ✅ sheet */}
      <ProductDetailSheet open={detailOpen} product={selected} onClose={closeDetail} />
    </div>
  );
}

function AssistantBubble({ content }: { content?: string }) {
  if (typeof content !== "string" || content.length === 0) return null;
  const blocks = useMemo(() => splitTextAndJsonBlocks(content), [content]);

  return (
    <div className="bg-white text-[#333] border border-gray-100 rounded-[22px] rounded-tl-none shadow-sm p-4 px-5 max-w-[85%] sm:max-w-[700px]">
      <div className="space-y-3">
        {blocks.map((b, idx) => {
          if (b.kind === "text") {
            return (
              <div key={idx} className="whitespace-pre-wrap text-[15px] leading-relaxed">
                {b.value.trim()}
              </div>
            );
          }
          const raw = b.value?.trim?.() ?? "";
          const parsed = safeJsonParse<any>(raw);
          if (isProductResult(parsed)) return <ProductCarousel key={idx} data={parsed} />;
          if (isSlotState(parsed)) return <SlotCarousel key={idx} state={parsed} />;

          return (
            <details key={idx} className="rounded-xl bg-[#F7F9FD] border border-gray-100 p-3">
              <summary className="cursor-pointer text-xs font-semibold" style={{ color: KB.primary }}>
                JSON 보기
              </summary>
              <pre className="mt-2 text-xs overflow-x-auto">{raw}</pre>
            </details>
          );
        })}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMsg: ChatMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const sessionId = process.env.NEXT_PUBLIC_SESSION_ID || "default_user";
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg.content, session_id: sessionId }),
      });

      const data = await res.json();

      const replyText =
        typeof data?.reply === "string"
          ? data.reply
          : typeof data === "string"
          ? data
          : JSON.stringify(data, null, 2);

      setMessages((prev) => [...prev, { role: "assistant", content: replyText }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "연결이 원활하지 않습니다. 다시 시도해주세요." },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="flex flex-col h-screen" style={{ background: KB.bg, color: "#1F2937" }}>
      <Header title="금융 탐정 에이전트" />

      {/* ✅ Products처럼 max-w-5xl */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto w-full px-4 py-6 space-y-6">
          {messages.length === 0 && (
            <div className="text-center py-10 space-y-3">
              <p className="text-xl font-semibold text-gray-800">안녕하세요, 고객님!</p>
              <p className="text-sm text-gray-500">어떤 금융 상품을 찾아드릴까요?</p>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              {m.role === "user" ? (
                <div
                  className="p-4 px-5 rounded-[22px] rounded-tr-none max-w-[85%] sm:max-w-[620px] text-[15px] leading-relaxed shadow-sm text-white"
                  style={{ background: KB.primary }}
                >
                  {m.content}
                </div>
              ) : (
                <AssistantBubble content={m.content} />
              )}
            </div>
          ))}

          {isLoading && <LoadingBubble />}
          <div ref={scrollRef} />
        </div>
      </div>

      {/* ✅ 입력도 max-w-5xl */}
      <div className="p-4 bg-white border-t border-gray-100 pb-8">
        <div className="max-w-5xl mx-auto w-full flex items-center gap-3 bg-[#F3F6FB] p-2 rounded-full px-5 focus-within:ring-2 transition-all">
          <input
            className="flex-1 bg-transparent border-none outline-none py-2 text-[15px] text-black placeholder-gray-400"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="상품명이나 키워드를 입력해보세요"
          />
          <button
            onClick={sendMessage}
            disabled={isLoading || !input.trim()}
            className="w-10 h-10 flex items-center justify-center text-white rounded-full disabled:bg-gray-300 transition-colors shadow-md"
            style={{ background: KB.primary }}
            type="button"
            aria-label="전송"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 10l7-7m0 0l7 7m-7-7v18" />
            </svg>
          </button>
        </div>
      </div>
    </main>
  );
}
