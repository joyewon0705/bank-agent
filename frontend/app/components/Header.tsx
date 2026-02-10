"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import RightSheet from "./RightSheet";

const KB = { primary: "#0114A7", gray050: "#EDF1F7" };

export default function Header({ title }: { title: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const go = (to: string) => {
    setOpen(false);
    router.push(to);
  };

  return (
    <>
      <header className="sticky top-0 z-10 bg-white border-b border-gray-100 shadow-sm">
        <div className="relative flex items-center justify-between px-5 py-4 max-w-5xl mx-auto w-full">
          {/* ✅ 홈 버튼 */}
          <button
            type="button"
            onClick={() => router.push("/")}
            className="w-10 h-10 grid place-items-center text-gray-600 hover:bg-gray-50 rounded-full"
            aria-label="홈으로"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M3 10.5L12 3l9 7.5V21a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1v-10.5z"
              />
            </svg>
          </button>

          {/* 타이틀 (가운데 고정) */}
          <div className="absolute left-1/2 -translate-x-1/2">
            <h1
              className="text-[17px] font-bold tracking-tight"
              style={{ color: KB.primary }}
            >
              {title}
            </h1>
          </div>

          {/* 메뉴 버튼 */}
          <button
            onClick={() => setOpen(true)}
            className="w-10 h-10 grid place-items-center text-gray-600 hover:bg-gray-50 rounded-full"
            aria-label="메뉴"
            type="button"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
        </div>
      </header>

      {/* 오른쪽 시트 */}
      <RightSheet open={open} onClose={() => setOpen(false)} title="바로가기">
        <div className="space-y-3">
          <button
            type="button"
            onClick={() => go("/chat")}
            className="w-full text-left p-4 rounded-2xl border border-gray-100 shadow-sm"
            style={{ background: pathname.startsWith("/chat") ? KB.gray050 : "white" }}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold" style={{ color: KB.primary }}>
                  챗봇 추천
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  대화로 조건을 모으고 추천 받아요
                </div>
              </div>
              <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </button>

          <button
            type="button"
            onClick={() => go("/products")}
            className="w-full text-left p-4 rounded-2xl border border-gray-100 shadow-sm"
            style={{ background: pathname.startsWith("/products") ? KB.gray050 : "white" }}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold" style={{ color: KB.primary }}>
                  상품 모아보기
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  유형/검색/정렬로 전체 상품 보기
                </div>
              </div>
              <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </button>

          <div className="pt-2">
            <div className="text-xs text-gray-400 mb-2">빠른 필터</div>
            <div className="flex flex-wrap gap-2">
              {["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => go(`/products?type=${encodeURIComponent(t)}`)}
                  className="px-4 py-2 rounded-full bg-white border border-gray-100 shadow-sm text-sm"
                  style={{ color: KB.primary }}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        </div>
      </RightSheet>
    </>
  );
}
