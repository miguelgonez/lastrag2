import React, { useState, useRef, useEffect } from "react";
import { Message, Source } from "../types";
import { Send, Sparkles, AlertCircle, FileText, Bot, User, BookmarkPlus } from "lucide-react";
import { motion } from "motion/react";

interface ChatPanelProps {
  messages: Message[];
  sources: Source[];
  selectedSourceIds: string[];
  onSendMessage: (query: string) => void;
  onSelectSource: (sourceId: string) => void;
  onSaveResponseAsNote: (text: string, title?: string) => void;
  isLoading: boolean;
}

export default function ChatPanel({
  messages,
  sources,
  selectedSourceIds,
  onSendMessage,
  onSelectSource,
  onSaveResponseAsNote,
  isLoading,
}: ChatPanelProps) {
  const [query, setQuery] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when messages load
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const activeSources = sources.filter((s) => selectedSourceIds.includes(s.id));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isLoading) return;
    onSendMessage(query.trim());
    setQuery("");
  };

  // Generate dynamic suggested questions based on selected documents
  const getSuggestedQuestions = () => {
    if (activeSources.length === 0) {
      return ["How do I get started?", "What kind of documents can I upload?", "Explain what NotebookLM is."];
    }
    
    const questions: string[] = [];
    
    // Check for voyager
    if (activeSources.some(s => s.id === "sample-voyager")) {
      questions.push("What is carrying the Golden Record on Voyager?", "When did Voyager 1 enter interstellar space?");
    }
    // Check for coffee
    if (activeSources.some(s => s.id === "sample-coffee")) {
      questions.push("Who discovered coffee according to Ethiopian legend?", "What is the difference between Arabica and Robusta?");
    }
    // Check for vite
    if (activeSources.some(s => s.id === "sample-vite")) {
      questions.push("Why does Vite start up faster than Webpack?", "How does esbuild speed up Vite dependencies?");
    }

    // Default fallbacks if custom documents
    if (questions.length < 3) {
      activeSources.forEach(s => {
        if (questions.length < 3) {
          questions.push(`Provide an executive summary of "${s.title}".`);
          questions.push(`What are the key takeaways from "${s.title}"?`);
        }
      });
    }

    return questions.slice(0, 3);
  };

  // Custom parser to render citations as clickable nodes
  const renderMessageContent = (text: string) => {
    // Regex matches [Document Title] or [Index]
    // Let's match bracketed content, e.g. [The Voyager Spacecraft Mission]
    const parts = text.split(/(\[[^\]]+\])/);
    
    return parts.map((part, index) => {
      if (part.startsWith("[") && part.endsWith("]")) {
        const titleContent = part.slice(1, -1).trim();
        
        // Find matching source
        // Let's do a case-insensitive search or contains
        const matchedSource = sources.find(s => 
          s.title.toLowerCase().includes(titleContent.toLowerCase()) ||
          titleContent.toLowerCase().includes(s.title.toLowerCase())
        );

        if (matchedSource) {
          return (
            <button
              key={index}
              onClick={() => onSelectSource(matchedSource.id)}
              className="inline-flex items-center gap-0.5 bg-indigo-50 border border-indigo-200 hover:bg-indigo-100 hover:border-indigo-300 text-indigo-700 text-[11px] font-semibold px-1.5 py-0.5 rounded mx-0.5 transition cursor-pointer shrink-0"
              title={`Click to read source: ${matchedSource.title}`}
            >
              <FileText className="w-2.5 h-2.5" />
              {matchedSource.title.split(" ").slice(0, 2).join(" ")}...
            </button>
          );
        }
      }
      return <span key={index} className="whitespace-pre-wrap">{part}</span>;
    });
  };

  return (
    <div className="flex flex-col h-full bg-white" id="chat-panel-container">
      {/* Active Sources Count Bar */}
      <div className="bg-indigo-50/50 border-b border-indigo-100/50 px-4 py-2 flex items-center justify-between">
        <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
          <Bot className="w-4 h-4 text-indigo-600" />
          AI Grounding Workspace
        </span>
        <span className="text-xs font-mono font-medium text-indigo-700 bg-indigo-100/60 px-2 py-0.5 rounded-full">
          {activeSources.length} of {sources.length} sources selected
        </span>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6" id="chat-messages-scroll">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col justify-center items-center text-center p-6 space-y-4 max-w-md mx-auto">
            <div className="w-12 h-12 bg-indigo-100/60 rounded-2xl flex items-center justify-center text-indigo-600 shadow-xs">
              <Sparkles className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-800 text-base">NotebookLM Grounded Chat</h3>
              <p className="text-xs text-slate-500 mt-2 leading-relaxed">
                Ask anything about your sources. The AI will answer utilizing details ONLY from the selected sources, providing inline citations.
              </p>
            </div>

            {activeSources.length === 0 && (
              <div className="p-3 bg-amber-50 border border-amber-100 rounded-xl flex items-start gap-2 text-left text-[11px] text-amber-800">
                <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold">No sources active!</span> Please select at least one document or sample resource from the sidebar to start asking grounded questions.
                </div>
              </div>
            )}

            {/* Suggested Questions */}
            <div className="w-full pt-4 space-y-2">
              <p className="text-[10px] text-slate-400 font-semibold tracking-wider uppercase">Suggested Grounding Questions</p>
              <div className="grid grid-cols-1 gap-2">
                {getSuggestedQuestions().map((q, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSendMessage(q)}
                    disabled={activeSources.length === 0 && idx > 0}
                    className="w-full text-left text-xs p-2.5 bg-slate-50 hover:bg-indigo-50 border border-slate-200 hover:border-indigo-200 rounded-lg text-slate-600 hover:text-indigo-900 transition font-medium cursor-pointer disabled:opacity-50 disabled:hover:bg-slate-50"
                  >
                    "{q}"
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-6 max-w-2xl mx-auto w-full">
            {messages.map((m) => {
              const isUser = m.role === "user";
              return (
                <div
                  key={m.id}
                  className={`flex gap-4 ${
                    isUser ? "flex-row-reverse" : ""
                  }`}
                  id={`chat-message-${m.id}`}
                >
                  {/* Sleek Avatar Icon */}
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm ${
                      isUser
                        ? "bg-gradient-to-tr from-indigo-500 to-purple-500 text-white"
                        : "bg-indigo-600 text-white shadow-md shadow-indigo-100"
                    }`}
                  >
                    {isUser ? (
                      <span className="text-[10px] font-bold">U</span>
                    ) : (
                      <Bot className="w-4 h-4 text-white" />
                    )}
                  </div>

                  {/* Message Bubble */}
                  <div className={`space-y-1 max-w-[85%] ${isUser ? "text-right" : ""}`}>
                    <div
                      className={`p-5 rounded-2xl text-sm leading-relaxed text-slate-700 shadow-xs border ${
                        isUser
                          ? "bg-indigo-50/70 border-indigo-100/60 rounded-tr-none text-indigo-950 text-left"
                          : "bg-white border-slate-200 rounded-tl-none text-left"
                      }`}
                    >
                      {renderMessageContent(m.content)}
                    </div>

                    {/* Bubble Footer Action */}
                    {!isUser && (
                      <div className="flex justify-start pr-1 pt-0.5">
                        <button
                          onClick={() => onSaveResponseAsNote(m.content, `Chat Clip - ${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`)}
                          className="inline-flex items-center gap-1.5 text-[10px] text-slate-400 hover:text-indigo-600 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg px-2 py-1 transition shadow-2xs cursor-pointer"
                          title="Save response as note card"
                          id={`btn-save-message-note-${m.id}`}
                        >
                          <BookmarkPlus className="w-3.5 h-3.5" />
                          Save to notes
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {isLoading && (
              <div className="flex gap-4">
                <div className="w-8 h-8 rounded-full bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-md shadow-indigo-100">
                  <Bot className="w-4 h-4 animate-bounce" />
                </div>
                <div className="bg-white border border-slate-200 p-5 rounded-2xl rounded-tl-none text-sm text-slate-400 flex items-center gap-3 shadow-xs">
                  <div className="flex gap-1.5">
                    <span className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                  NotebookLM is reading documents...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Message Input Bar (Sleek Interface style) */}
      <div className="p-6 shrink-0 border-t border-slate-100 bg-[#F9FAFB]">
        <div className="max-w-2xl mx-auto relative">
          <form onSubmit={handleSubmit}>
            <input
              type="text"
              placeholder={
                activeSources.length === 0
                  ? "Select sources in the left panel to start chatting..."
                  : "Ask about your sources..."
              }
              disabled={activeSources.length === 0 || isLoading}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full text-sm py-4 pl-6 pr-14 bg-white border border-slate-200 rounded-2xl shadow-xl focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all placeholder:text-slate-400 disabled:opacity-50"
              id="chat-query-input"
            />
            <button
              type="submit"
              disabled={!query.trim() || isLoading || activeSources.length === 0}
              className="absolute right-3 top-3 w-10 h-10 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-100 text-white disabled:text-slate-400 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-200 transition-transform active:scale-95 cursor-pointer"
              id="chat-send-submit"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
        <p className="mt-3 text-center text-[10px] text-slate-400">
          NotebookLM can make mistakes. Verify important information.
        </p>
      </div>
    </div>
  );
}
