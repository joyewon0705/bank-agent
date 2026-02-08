import "./globals.css";

export const metadata = {
  title: "금융 탐정 에이전트",
  description: "챗봇 추천 + 상품 모아보기",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="antialiased">{children}</body>
    </html>
  );
}
