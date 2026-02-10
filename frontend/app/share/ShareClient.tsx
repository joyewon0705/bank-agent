"use client";

import { useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

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

const KB = { primary: "#0114A7", gray050: "#EDF1F7" };

function base64UrlDecode(b64url: string) {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  return decodeURIComponent(escape(window.atob(b64 + pad)));
}

export default function ShareClient() {
  const sp = useSearchParams();
  const router = useRouter();
  const [toast, setToast] = useState("");

  const decoded = useMemo(() => {
    const raw = sp.get("data");
    if (!raw) return null;
    try {
      const obj = JSON.parse(base64UrlDecode(raw));
      return obj?.data?.products ? obj.data : obj;
    } catch {
      return null;
    }
  }, [sp]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 1600);
  };

  const copyLink = async () => {
    await navigator.clipboard.writeText(window.location.href);
    showToast("링크를 복사했어요");
  };

  if (!decoded) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-6">
        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="text-lg font-bold">유효하지 않은 링크예요</div>
          <button
            onClick={() => router.push("/chat")}
            className="mt-4 px-4 py-2 rounded-xl text-white"
            style={{ background: KB.primary }}
          >
            챗으로 가기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
      {/* 여기 아래는 네가 이미 만든 카드 UI 그대로 */}
      {/* toast도 그대로 */}
      {toast && (
        <div className="fixed bottom-24 left-1/2 -translate-x-1/2 bg-black/80 text-white px-4 py-2 rounded-full">
          {toast}
        </div>
      )}
    </div>
  );
}
