"use client";

import { useState, useRef, useEffect } from "react";

export default function Home() {
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 메시지 추가될 때마다 바닥으로 스크롤
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMsg = { role: "user", content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input }),
      });
      const data = await response.json();
      setMessages(prev => [...prev, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: "assistant", content: "서버 연결에 실패했습니다." }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="max-w-2xl mx-auto h-screen flex flex-col p-4">
      <h1 className="text-2xl font-bold p-4 text-center border-b">🏦 AI 뱅킹 에이전트</h1>
      
      {/* 메시지 영역 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`p-3 rounded-lg max-w-[80%] ${m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}>
              {m.content}
            </div>
          </div>
        ))}
        {isLoading && <div className="text-gray-400 animate-pulse">AI가 생각 중입니다...</div>}
        <div ref={scrollRef} />
      </div>

      {/* 입력 영역 */}
      <div className="flex gap-2 p-4 border-t">
        <input 
          className="flex-1 border p-2 rounded text-black"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
          placeholder="금융 상품에 대해 물어보세요!"
        />
        <button 
          onClick={sendMessage}
          disabled={isLoading}
          className="bg-blue-600 text-white px-4 py-2 rounded disabled:bg-gray-400"
        >
          전송
        </button>
      </div>
    </main>
  );
}