import { Suspense } from "react";
import Header from "../components/Header";
import ShareClient from "./ShareClient";

export default function SharePage() {
  return (
    <main className="min-h-screen bg-[#F7F9FD] text-[#1F2937]">
      <Header title="추천 결과 공유" />

      <Suspense
        fallback={
          <div className="max-w-5xl mx-auto px-4 py-10">
            <div className="bg-white rounded-2xl p-6 shadow-sm text-center text-gray-500">
              추천 결과를 불러오는 중이에요…
            </div>
          </div>
        }
      >
        <ShareClient />
      </Suspense>
    </main>
  );
}
