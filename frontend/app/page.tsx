"use client";

import { useState, useRef, useEffect } from "react";

export default function Home() {
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

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
      setMessages(prev => [...prev, { role: "assistant", content: "연결이 원활하지 않습니다. 다시 시도해주세요." }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    // 배경색을 케이뱅크 특유의 아주 밝은 그레이(#F7F9FD)로 설정
    <main className="flex flex-col h-screen bg-[#F7F9FD] text-[#1F2937]">
      
      {/* Header: 상단 바 스타일 고도화 */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-5 py-4 bg-white border-b border-gray-100 shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-[#0114A7] rounded-full flex items-center justify-center">
            <span className="text-white text-[10px] font-bold">KB</span>
          </div>
          <h1 className="text-lg font-bold tracking-tight text-[#0114A7]">금융 탐정 에이전트</h1>
        </div>
        <button className="text-gray-400">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
      </header>
      
      {/* 메시지 영역: 모바일 앱 같은 스크롤 영역 */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6 max-w-2xl mx-auto w-full">
        {messages.length === 0 && (
          <div className="text-center py-10 space-y-3">
            <p className="text-xl font-semibold text-gray-800">안녕하세요, 고객님!</p>
            <p className="text-sm text-gray-500">어떤 금융 상품을 찾아드릴까요?</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-2`}>
            <div className={`
              relative p-4 px-5 rounded-[22px] max-w-[85%] text-[15px] leading-relaxed shadow-sm
              ${m.role === 'user' 
                ? 'bg-[#0114A7] text-white rounded-tr-none' 
                : 'bg-white text-[#333] border border-gray-100 rounded-tl-none'}
            `}>
              {m.content}
            </div>
          </div>
        ))}
        
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-100 p-4 rounded-[22px] rounded-tl-none shadow-sm">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-300 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                <div className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.3s]"></div>
              </div>
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {/* 입력 영역: 하단 고정형 플로팅 디자인 */}
      <div className="p-4 bg-white border-t border-gray-100 pb-8">
        <div className="max-w-2xl mx-auto flex items-center gap-3 bg-[#F3F6FB] p-2 rounded-full px-5 focus-within:ring-2 focus-within:ring-[#4262FF] transition-all">
          <input 
            className="flex-1 bg-transparent border-none outline-none py-2 text-[15px] text-black placeholder-gray-400"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="상품명이나 키워드를 입력해보세요"
          />
          <button 
            onClick={sendMessage}
            disabled={isLoading || !input.trim()}
            className="w-10 h-10 flex items-center justify-center bg-[#0114A7] text-white rounded-full disabled:bg-gray-300 transition-colors shadow-md"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 10l7-7m0 0l7 7m-7-7v18"></path></svg>
          </button>
        </div>
      </div>
    </main>
  );
}