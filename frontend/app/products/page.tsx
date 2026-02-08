"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Header from "../components/Header";

const KB = { primary: "#0114A7", bg: "#F7F9FD", gray050: "#EDF1F7" };

type ProductItem = Record<string, any>;

function normName(p: ProductItem) {
  return p.product_name ?? p.fin_prdt_nm ?? p.name ?? "상품명";
}
function normBank(p: ProductItem) {
  return p.bank ?? p.fin_co_nm ?? p.kor_co_nm ?? "금융사";
}
function normRate(p: ProductItem) {
  const r = p.rate ?? p.max_rate ?? p.intr_rate2;
  if (r == null) return "";
  const s = String(r);
  return s.includes("%") ? s : `${s}%`;
}

const FALLBACK_TYPES = ["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"];

export default function ProductsPage() {
  const sp = useSearchParams();
  const presetType = sp.get("type");

  const [types, setTypes] = useState<string[]>(["전체", ...FALLBACK_TYPES]);
  const [type, setType] = useState<string>(presetType ? presetType : "전체");
  const [q, setQ] = useState<string>("");
  const [sort, setSort] = useState<string>("rate_desc");
  const [items, setItems] = useState<ProductItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string>("");

  useEffect(() => {
    // product-types 로딩: 백엔드가 {product_types:[...]} 형태면 그거 읽기
    (async () => {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/product-types`);
        if (!res.ok) throw new Error(`product-types ${res.status}`);
        const data = await res.json();
        const arr = Array.isArray(data) ? data : data?.product_types ?? data?.types;
        if (Array.isArray(arr) && arr.length > 0) setTypes(["전체", ...arr]);
      } catch {
        // 실패 시 fallback 유지
      }
    })();
  }, []);

  const fetchOneType = async (productType: string) => {
    const params = new URLSearchParams();
    params.set("product_type", productType); // ✅ 필수
    params.set("sort", sort);
    params.set("page", "1");
    params.set("page_size", "50");
    if (q.trim()) params.set("q", q.trim());
    const url = `${process.env.NEXT_PUBLIC_API_URL}/products?${params.toString()}`;

    const res = await fetch(url);
    const json = await res.json();

    if (!res.ok) {
      // 422면 보통 FastAPI validation detail이 옴
      throw new Error(`${res.status} ${JSON.stringify(json)}`);
    }

    // 백엔드가 list를 바로 주거나 {products:[...]} 형태일 수 있어 방어
    const list = Array.isArray(json) ? json : json?.products ?? json?.items ?? [];
    return Array.isArray(list) ? list : [];
  };

  const fetchProducts = async () => {
    setLoading(true);
    setErrorText("");
    try {
      if (type === "전체") {
        // ✅ 전체일 때: 모든 타입 병합 (422 방지)
        const allTypes = types.filter((t) => t !== "전체");
        const results = await Promise.allSettled(allTypes.map((t) => fetchOneType(t)));
        const merged: ProductItem[] = [];
        for (const r of results) {
          if (r.status === "fulfilled") merged.push(...r.value);
        }
        setItems(merged);
      } else {
        const list = await fetchOneType(type);
        setItems(list);
      }
    } catch (e: any) {
      setItems([]);
      setErrorText(e?.message ?? "상품 조회 실패");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, sort]);

  const count = items.length;

  return (
    <main className="flex flex-col min-h-screen" style={{ background: KB.bg, color: "#1F2937" }}>
      <Header title="상품 모아보기" />

      <div className="max-w-2xl mx-auto w-full px-4 py-5 space-y-4">
        <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-4 space-y-3">
          <div className="flex gap-2 overflow-x-auto [-webkit-overflow-scrolling:touch]">
            {types.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setType(t)}
                className="h-9 px-4 rounded-full text-sm font-semibold border shrink-0"
                style={
                  type === t
                    ? { background: KB.primary, color: "white", borderColor: KB.primary }
                    : { background: "white", color: KB.primary, borderColor: "#E5E7EB" }
                }
              >
                {t}
              </button>
            ))}
          </div>

          <div className="flex gap-2">
            <div className="flex-1 bg-[#F3F6FB] rounded-full px-4 py-2 flex items-center">
              <svg className="w-5 h-5 text-gray-400 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-4.35-4.35m0 0A7.5 7.5 0 103.75 3.75a7.5 7.5 0 0012.9 12.9z" />
              </svg>
              <input
                className="w-full bg-transparent outline-none text-sm"
                placeholder="상품명/금융사 검색"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && fetchProducts()}
              />
            </div>

            <button
              type="button"
              onClick={fetchProducts}
              className="h-10 px-4 rounded-full text-sm font-semibold"
              style={{ background: KB.primary, color: "white" }}
            >
              검색
            </button>
          </div>

          <div className="flex items-center justify-between">
            <div className="text-xs text-gray-500">총 {count}개</div>
            <select
              className="h-9 rounded-full border border-gray-200 bg-white px-3 text-sm"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="rate_desc">금리 높은 순</option>
              <option value="rate_asc">금리 낮은 순</option>
              <option value="name_asc">이름순</option>
              <option value="bank_asc">금융사순</option>
            </select>
          </div>
        </div>

        {errorText && (
          <div className="bg-white border border-red-100 rounded-2xl p-4 text-sm text-red-600">
            상품을 가져오지 못했어요: {errorText}
          </div>
        )}

        <div className="space-y-3 pb-10">
          {loading && <div className="text-sm text-gray-500 py-8 text-center">불러오는 중…</div>}
          {!loading && items.length === 0 && !errorText && (
            <div className="text-sm text-gray-500 py-10 text-center">조건에 맞는 상품이 없어요.</div>
          )}

          {items.map((p, idx) => (
            <div key={idx} className="bg-white border border-gray-100 rounded-2xl shadow-sm p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="text-xs text-gray-500">{normBank(p)}</div>
                {normRate(p) ? (
                  <div className="text-sm font-bold" style={{ color: KB.primary }}>
                    {normRate(p)}
                  </div>
                ) : null}
              </div>

              <div className="mt-1 text-[15px] font-semibold text-gray-900">{normName(p)}</div>

              {(p.join_way || p.etc_note) && (
                <div className="mt-2 text-xs text-gray-600 line-clamp-3">
                  {p.join_way ? `가입방법: ${p.join_way}` : ""}
                  {p.join_way && p.etc_note ? " · " : ""}
                  {p.etc_note ? p.etc_note : ""}
                </div>
              )}

              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  className="h-10 flex-1 rounded-xl text-sm font-semibold"
                  style={{ background: KB.gray050, color: KB.primary }}
                >
                  상세
                </button>
                <button
                  type="button"
                  className="h-10 flex-1 rounded-xl text-sm font-semibold"
                  style={{ background: KB.primary, color: "white" }}
                >
                  담기
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
