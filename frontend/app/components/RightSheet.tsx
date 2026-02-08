"use client";

import { useEffect } from "react";

export default function RightSheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      {/* backdrop */}
      <button
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="닫기"
        type="button"
      />

      {/* right sheet */}
      <div className="absolute inset-y-0 right-0 flex">
        <div
          className="
            h-full bg-white border-l border-gray-100 shadow-2xl
            w-[85vw] sm:w-[420px] md:w-[50vw] md:max-w-[520px]
            translate-x-0
          "
        >
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <div className="text-sm font-semibold text-gray-900">{title ?? "메뉴"}</div>
            <button
              onClick={onClose}
              className="w-10 h-10 grid place-items-center text-gray-400"
              aria-label="닫기"
              type="button"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="h-[calc(100%-64px)] overflow-y-auto px-5 py-4">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
