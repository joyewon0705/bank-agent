"use client";

import { useEffect, useState } from "react";
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
function normCondition(p: ProductItem) {
  return (
    p.special_condition_raw ??
    p.special_condition ??
    p.spcl_cnd ??
    p.etc_note ??
    p.join_way ??
    ""
  );
}
function normBaseRate(p: ProductItem) {
  const r = p.base_rate ?? p.intr_rate ?? p.rate_base;
  if (r == null) return "";
  const s = String(r);
  return s.includes("%") ? s : `${s}%`;
}
function normTerm(p: ProductItem) {
  return p.term ?? p.save_trm ?? p.join_period ?? "";
}
function normType(p: ProductItem) {
  return p.product_type ?? p.prdt_div ?? p.type ?? "";
}

const FALLBACK_TYPES = ["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"];

function ProductCard({
  p,
  onDetail,
}: {
  p: ProductItem;
  onDetail?: () => void;
}) {
  const bank = normBank(p);
  const name = normName(p);
  const rate = normRate(p);
  const cond = normCondition(p);

  return (
    <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-gray-500 truncate">{bank}</div>
          <div className="mt-1 text-[15px] font-semibold text-gray-900 leading-snug line-clamp-2">
            {name}
          </div>
        </div>

        {rate ? (
          <div
            className="shrink-0 px-3 py-1 rounded-full text-sm font-extrabold"
            style={{ background: "rgba(1,20,167,0.08)", color: KB.primary }}
            aria-label={`최고금리 ${rate}`}
          >
            {rate}
          </div>
        ) : null}
      </div>

      {cond ? (
        <div className="mt-3 rounded-xl bg-[#F7F9FD] px-3 py-2">
          <div className="text-[11px] font-semibold" style={{ color: KB.primary }}>
            우대조건 미리보기
          </div>
          <div className="mt-1 text-xs text-gray-700 leading-relaxed line-clamp-2 whitespace-pre-line">
            {cond}
          </div>
        </div>
      ) : null}

      {/* ✅ 담기 버튼 제거, 상세만 풀폭 */}
      <div className="mt-4">
        <button
          type="button"
          onClick={onDetail}
          className="h-10 w-full rounded-xl text-sm font-semibold transition active:scale-[0.99]"
          style={{ background: KB.primary, color: "white" }}
        >
          상세보기
        </button>
      </div>
    </div>
  );
}

function DetailSheet({
  open,
  product,
  onClose,
}: {
  open: boolean;
  product: ProductItem | null;
  onClose: () => void;
}) {
  if (!open || !product) return null;

  const bank = normBank(product);
  const name = normName(product);
  const maxRate = normRate(product);
  const baseRate = normBaseRate(product);
  const cond = normCondition(product);
  const term = normTerm(product);
  const type = normType(product);
  const code = product.fin_prdt_cd ?? product.fin_prdt_cd2 ?? product.id ?? "";

  const Row = ({ label, value }: { label: string; value: any }) => {
    if (value == null || String(value).trim() === "") return null;
    return (
      <div className="flex gap-3 py-2">
        <div className="w-24 shrink-0 text-xs text-gray-500">{label}</div>
        <div className="flex-1 text-sm text-gray-900 break-words whitespace-pre-line">{String(value)}</div>
      </div>
    );
  };

  return (
    <>
      {/* overlay */}
      <div
        className="fixed inset-0 z-50 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* sheet/modal */}
      <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6">
        <div
          className="
            w-full sm:max-w-2xl
            bg-white
            rounded-t-3xl sm:rounded-3xl
            shadow-xl
            max-h-[86vh]
            overflow-hidden
          "
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

            <div className="mt-3 flex flex-wrap gap-2">
              {type ? (
                <span className="px-3 py-1 rounded-full text-xs font-semibold border border-gray-200 text-gray-700">
                  {type}
                </span>
              ) : null}
              {term ? (
                <span className="px-3 py-1 rounded-full text-xs font-semibold border border-gray-200 text-gray-700">
                  기간 {term}
                </span>
              ) : null}
              {baseRate ? (
                <span
                  className="px-3 py-1 rounded-full text-xs font-semibold"
                  style={{ background: "rgba(1,20,167,0.08)", color: KB.primary }}
                >
                  기본 {baseRate}
                </span>
              ) : null}
              {maxRate ? (
                <span
                  className="px-3 py-1 rounded-full text-xs font-extrabold"
                  style={{ background: "rgba(1,20,167,0.12)", color: KB.primary }}
                >
                  최고 {maxRate}
                </span>
              ) : null}
            </div>
          </div>

          {/* body */}
          <div className="px-5 py-4 overflow-y-auto max-h-[calc(86vh-140px)]">
            <div className="rounded-2xl bg-[#F7F9FD] p-4">
              <div className="text-xs font-bold" style={{ color: KB.primary }}>
                우대조건 / 특약
              </div>
              <div className="mt-2 text-sm text-gray-800 leading-relaxed whitespace-pre-line">
                {cond ? cond : "제공 정보 없음"}
              </div>
            </div>

            <div className="mt-4">
              <div className="text-xs font-bold text-gray-900">기본 정보</div>
              <div className="mt-2 rounded-2xl border border-gray-100 bg-white px-4 py-2">
                <Row label="금융사" value={bank} />
                <Row label="상품코드" value={code} />
                <Row label="상품유형" value={type} />
                <Row label="기간" value={term} />
                <Row label="기본금리" value={baseRate} />
                <Row label="최고금리" value={maxRate} />
              </div>
            </div>

            {/* 필요하면 여기 더 붙이기: 가입방법, 대상, 유의사항 등 */}
            {(product.join_way || product.join_member || product.etc_note) && (
              <div className="mt-4">
                <div className="text-xs font-bold text-gray-900">추가 안내</div>
                <div className="mt-2 rounded-2xl border border-gray-100 bg-white px-4 py-2">
                  <Row label="가입방법" value={product.join_way} />
                  <Row label="가입대상" value={product.join_member} />
                  <Row label="유의사항" value={product.etc_note} />
                </div>
              </div>
            )}
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

  // ✅ 상세 시트 상태
  const [detailOpen, setDetailOpen] = useState(false);
  const [selected, setSelected] = useState<ProductItem | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/product-types`);
        if (!res.ok) throw new Error(`product-types ${res.status}`);
        const data = await res.json();
        const arr = Array.isArray(data) ? data : data?.product_types ?? data?.types;
        if (Array.isArray(arr) && arr.length > 0) setTypes(["전체", ...arr]);
      } catch {
        // fallback 유지
      }
    })();
  }, []);

  const fetchOneType = async (productType: string) => {
    const params = new URLSearchParams();
    params.set("product_type", productType);
    params.set("sort", sort);
    params.set("page", "1");
    params.set("page_size", "50");
    if (q.trim()) params.set("q", q.trim());
    const url = `${process.env.NEXT_PUBLIC_API_URL}/products?${params.toString()}`;

    const res = await fetch(url);
    const json = await res.json();
    if (!res.ok) throw new Error(`${res.status} ${JSON.stringify(json)}`);

    const list = Array.isArray(json) ? json : json?.products ?? json?.items ?? [];
    return Array.isArray(list) ? list : [];
  };

  const fetchProducts = async () => {
    setLoading(true);
    setErrorText("");
    try {
      if (type === "전체") {
        const allTypes = types.filter((t) => t !== "전체");
        const results = await Promise.allSettled(allTypes.map((t) => fetchOneType(t)));
        const merged: ProductItem[] = [];
        for (const r of results) if (r.status === "fulfilled") merged.push(...r.value);
        setItems(merged);
      } else {
        setItems(await fetchOneType(type));
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

  const openDetail = (p: ProductItem) => {
    setSelected(p);
    setDetailOpen(true);
  };
  const closeDetail = () => {
    setDetailOpen(false);
    setSelected(null);
  };

  return (
    <main className="flex flex-col min-h-screen" style={{ background: KB.bg, color: "#1F2937" }}>
      <Header title="상품 모아보기" />

      <div className="max-w-5xl mx-auto w-full px-4 py-5 space-y-4">
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
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M21 21l-4.35-4.35m0 0A7.5 7.5 0 103.75 3.75a7.5 7.5 0 0012.9 12.9z"
                />
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

        <div className="pb-10">
          {loading && <div className="text-sm text-gray-500 py-8 text-center">불러오는 중…</div>}
          {!loading && items.length === 0 && !errorText && (
            <div className="text-sm text-gray-500 py-10 text-center">조건에 맞는 상품이 없어요.</div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {items.map((p, idx) => (
              <ProductCard key={idx} p={p} onDetail={() => openDetail(p)} />
            ))}
          </div>
        </div>
      </div>

      {/* ✅ 상세 바텀시트/모달 */}
      <DetailSheet open={detailOpen} product={selected} onClose={closeDetail} />
    </main>
  );
}
