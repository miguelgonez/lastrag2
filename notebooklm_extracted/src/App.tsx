import React, { useState, useEffect } from "react";
import { Source, Note, Message } from "./types";
import { SAMPLE_SOURCES } from "./data/sampleSources";
import SourceList from "./components/SourceList";
import DocumentViewer from "./components/DocumentViewer";
import NotesGrid from "./components/NotesGrid";
import ChatPanel from "./components/ChatPanel";
import NotebookGuide from "./components/NotebookGuide";
import {
  FileText,
  Bookmark,
  MessageSquare,
  Compass,
  Sparkles,
  BookMarked,
  Layers,
  CheckCircle2,
  AlertCircle
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export default function App() {
  // Sources state (initialize with preloaded samples)
  const [sources, setSources] = useState<Source[]>(() => {
    const saved = localStorage.getItem("notebooklm-sources");
    return saved ? JSON.parse(saved) : SAMPLE_SOURCES;
  });

  // Selected (checked) source IDs for context (default to all sample sources active on boot)
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>(() => {
    const saved = localStorage.getItem("notebooklm-selected-source-ids");
    if (saved) return JSON.parse(saved);
    // Default: Check all sample sources
    return SAMPLE_SOURCES.map((s) => s.id);
  });

  // Active source ID for the left panel document reader
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);

  // Keep-style Notes Board state
  const [notes, setNotes] = useState<Note[]>(() => {
    const saved = localStorage.getItem("notebooklm-notes");
    return saved ? JSON.parse(saved) : [];
  });

  // Chat conversation state
  const [messages, setMessages] = useState<Message[]>(() => {
    const saved = localStorage.getItem("notebooklm-messages");
    return saved ? JSON.parse(saved) : [];
  });

  // Tabs states
  const [leftTab, setLeftTab] = useState<"sources" | "notes">("sources");
  const [rightTab, setRightTab] = useState<"chat" | "guide">("chat");

  // Loading states
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [appError, setAppError] = useState<string | null>(null);

  // Persistence triggers
  useEffect(() => {
    localStorage.setItem("notebooklm-sources", JSON.stringify(sources));
  }, [sources]);

  useEffect(() => {
    localStorage.setItem("notebooklm-selected-source-ids", JSON.stringify(selectedSourceIds));
  }, [selectedSourceIds]);

  useEffect(() => {
    localStorage.setItem("notebooklm-notes", JSON.stringify(notes));
  }, [notes]);

  useEffect(() => {
    localStorage.setItem("notebooklm-messages", JSON.stringify(messages));
  }, [messages]);

  // Actions: Source handling
  const handleAddTextSource = (title: string, content: string) => {
    const wordCount = content.trim().split(/\s+/).length;
    const newSource: Source = {
      id: `text-${Date.now()}`,
      title,
      content,
      type: "text",
      wordCount,
    };
    setSources((prev) => [newSource, ...prev]);
    setSelectedSourceIds((prev) => [...prev, newSource.id]);
  };

  const handleAddUrlSource = async (url: string) => {
    setIsScraping(true);
    setAppError(null);
    try {
      const response = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      if (!response.ok) {
        throw new Error("Could not extract readable text from URL.");
      }

      const data = await response.json();
      const wordCount = data.text.split(/\s+/).length;
      const newSource: Source = {
        id: `url-${Date.now()}`,
        title: data.title || "Scraped Document",
        content: data.text,
        type: "url",
        url,
        wordCount,
      };

      setSources((prev) => [newSource, ...prev]);
      setSelectedSourceIds((prev) => [...prev, newSource.id]);
    } catch (err: any) {
      console.error(err);
      setAppError(err.message || "Failed to fetch website. Try copying and pasting raw text instead.");
    } finally {
      setIsScraping(false);
    }
  };

  const handleDeleteSource = (sourceId: string) => {
    setSources((prev) => prev.filter((s) => s.id !== sourceId));
    setSelectedSourceIds((prev) => prev.filter((id) => id !== sourceId));
    if (activeSourceId === sourceId) {
      setActiveSourceId(null);
    }
  };

  const handleToggleSourceSelection = (sourceId: string) => {
    setSelectedSourceIds((prev) =>
      prev.includes(sourceId)
        ? prev.filter((id) => id !== sourceId)
        : [...prev, sourceId]
    );
  };

  const handleToggleAllSources = (selected: boolean) => {
    if (selected) {
      setSelectedSourceIds(sources.map((s) => s.id));
    } else {
      setSelectedSourceIds([]);
    }
  };

  const handleSelectSource = (sourceId: string) => {
    setActiveSourceId(sourceId);
  };

  // Actions: Notes handling
  const handleAddNote = (title: string, content: string, color = "slate") => {
    const newNote: Note = {
      id: `note-${Date.now()}`,
      title,
      content,
      color,
      createdAt: new Date().toISOString(),
    };
    setNotes((prev) => [newNote, ...prev]);
  };

  const handleUpdateNote = (id: string, updates: Partial<Note>) => {
    setNotes((prev) =>
      prev.map((n) => (n.id === id ? { ...n, ...updates } : n))
    );
  };

  const handleDeleteNote = (id: string) => {
    setNotes((prev) => prev.filter((n) => n.id !== id));
  };

  const handleSaveSelectionAsNote = (text: string) => {
    const activeSource = sources.find((s) => s.id === activeSourceId);
    const title = activeSource ? `Clip from: ${activeSource.title}` : "Clipped Document Note";
    const newNote: Note = {
      id: `note-${Date.now()}`,
      title,
      content: text,
      color: "indigo",
      createdAt: new Date().toISOString(),
      sourceId: activeSource?.id,
      sourceTitle: activeSource?.title,
    };
    setNotes((prev) => [newNote, ...prev]);
    // Slide left to notes so user instantly sees they saved it!
    setLeftTab("notes");
    setActiveSourceId(null);
  };

  const handleSaveResponseAsNote = (text: string, title = "Chat Clip Note") => {
    const newNote: Note = {
      id: `note-${Date.now()}`,
      title,
      content: text,
      color: "sky",
      createdAt: new Date().toISOString(),
    };
    setNotes((prev) => [newNote, ...prev]);
    // Toggle notes tab
    setLeftTab("notes");
  };

  // Actions: Chat interaction
  const handleSendMessage = async (query: string) => {
    setIsLoadingChat(true);
    setAppError(null);

    // Append user message immediately
    const userMsg: Message = {
      id: `msg-user-${Date.now()}`,
      role: "user",
      content: query,
      timestamp: new Date().toISOString(),
    };
    const updatedMsgs = [...messages, userMsg];
    setMessages(updatedMsgs);

    // Compile active sources
    const activeSources = sources.filter((s) => selectedSourceIds.includes(s.id));

    try {
      const response = await fetch("/api/gemini/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sources: activeSources,
          messages: updatedMsgs.slice(-10), // Pass last 10 messages for conversational context
          query,
        }),
      });

      if (!response.ok) {
        throw new Error("NotebookLM server did not respond correctly.");
      }

      const data = await response.json();
      const modelMsg: Message = {
        id: `msg-model-${Date.now()}`,
        role: "model",
        content: data.text,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, modelMsg]);
    } catch (err: any) {
      console.error(err);
      setAppError(err.message || "Failed to generate response. Please try again.");
    } finally {
      setIsLoadingChat(false);
    }
  };

  const handleClearChat = () => {
    setMessages([]);
  };

  return (
    <div className="flex flex-col h-screen bg-[#F9FAFB] font-sans" id="applet-main-container">
      {/* Dynamic Alert Panel */}
      <AnimatePresence>
        {appError && (
          <motion.div
            initial={{ y: -50, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -50, opacity: 0 }}
            className="bg-red-500 text-white p-3.5 text-xs font-semibold flex items-center justify-between shadow-md z-50 absolute top-0 left-0 right-0"
            id="global-alert-toast"
          >
            <span className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {appError}
            </span>
            <button
              onClick={() => setAppError(null)}
              className="bg-red-700 hover:bg-red-800 px-2 py-1 rounded transition text-[10px] uppercase font-bold shrink-0 ml-4 cursor-pointer"
            >
              Dismiss
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Premium App Bar (Sleek Interface style) */}
      <header className="h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between shrink-0 select-none shadow-xs z-20">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">N</div>
          <div className="flex items-center text-sm font-medium text-slate-500">
            <span>My Notebooks</span>
            <span className="mx-2 text-slate-300">/</span>
            <span className="text-slate-900 font-semibold flex items-center gap-2">
              NotebookLM Studio
              <span className="text-[9px] font-bold bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded-full uppercase tracking-wider font-mono border border-indigo-100/60 shrink-0">
                Grounded AI
              </span>
            </span>
          </div>
        </div>

        {/* Global actions */}
        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button
              onClick={handleClearChat}
              className="text-xs font-semibold text-slate-500 hover:text-slate-800 transition px-2.5 py-1.5 hover:bg-slate-50 rounded-lg cursor-pointer"
              id="btn-clear-chat-history"
            >
              Clear Chat
            </button>
          )}

          {/* User Profile Avatar / Email style from mockup */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono font-medium text-slate-400 bg-slate-50 border border-slate-150 px-2.5 py-1 rounded-full hidden sm:inline-block">
              mjuliolorca@gmail.com
            </span>
            <div className="w-8 h-8 bg-gradient-to-tr from-indigo-500 to-purple-500 rounded-full border-2 border-white shadow-sm flex items-center justify-center text-white text-[10px] font-bold">MJ</div>
          </div>
        </div>
      </header>

      {/* Workspace Split Layout */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden relative" id="split-workspace-panels">
        
        {/* LEFT COLUMN: Sources & Notes Board (60% width) */}
        <section className="flex-1 md:flex-[6] flex flex-col overflow-hidden border-r border-slate-200">
          
          {/* Header Toggle bar (only show if not inside active reader) */}
          {activeSourceId === null && (
            <div className="bg-white border-b border-slate-200 px-4 py-2.5 flex justify-between items-center select-none shrink-0">
              <div className="flex bg-slate-100 p-1 rounded-lg">
                <button
                  onClick={() => setLeftTab("sources")}
                  className={`flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-semibold transition cursor-pointer ${
                    leftTab === "sources"
                      ? "bg-white text-slate-800 shadow-xs"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                  id="tab-toggle-sources"
                >
                  <FileText className="w-3.5 h-3.5" />
                  Sources
                </button>
                <button
                  onClick={() => setLeftTab("notes")}
                  className={`flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-semibold transition cursor-pointer ${
                    leftTab === "notes"
                      ? "bg-white text-slate-800 shadow-xs"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                  id="tab-toggle-notes"
                >
                  <Bookmark className="w-3.5 h-3.5" />
                  Notes Board
                </button>
              </div>

              {leftTab === "sources" && (
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                  {sources.length} Documents Loaded
                </span>
              )}
              {leftTab === "notes" && (
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-50 px-2 py-0.5 rounded-full border border-slate-150">
                  {notes.length} Cards saved
                </span>
              )}
            </div>
          )}

          {/* Left Main Viewport */}
          <div className="flex-1 overflow-hidden relative">
            <AnimatePresence mode="wait">
              {activeSourceId !== null ? (
                // Document Reader Mode
                <motion.div
                  key="reader"
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  className="h-full"
                >
                  {(() => {
                    const activeSource = sources.find((s) => s.id === activeSourceId);
                    if (!activeSource) return null;
                    return (
                      <DocumentViewer
                        source={activeSource}
                        onClose={() => setActiveSourceId(null)}
                        onSaveSelectionAsNote={handleSaveSelectionAsNote}
                      />
                    );
                  })()}
                </motion.div>
              ) : leftTab === "sources" ? (
                // Sources list Mode
                <motion.div
                  key="sources"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="h-full"
                >
                  <SourceList
                    sources={sources}
                    selectedSourceIds={selectedSourceIds}
                    activeSourceId={activeSourceId}
                    onSelectSource={handleSelectSource}
                    onToggleSourceSelection={handleToggleSourceSelection}
                    onToggleAllSources={handleToggleAllSources}
                    onAddTextSource={handleAddTextSource}
                    onAddUrlSource={handleAddUrlSource}
                    onDeleteSource={handleDeleteSource}
                    isScraping={isScraping}
                  />
                </motion.div>
              ) : (
                // Keep Notes Grid Mode
                <motion.div
                  key="notes"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="h-full"
                >
                  <NotesGrid
                    notes={notes}
                    onAddNote={handleAddNote}
                    onUpdateNote={handleUpdateNote}
                    onDeleteNote={handleDeleteNote}
                    onOpenSource={(sourceId) => {
                      setActiveSourceId(sourceId);
                    }}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </section>

        {/* RIGHT COLUMN: AI Chat & Notebook Guide (40% width) */}
        <section className="flex-1 md:flex-[4] flex flex-col bg-white overflow-hidden shadow-2xl shadow-slate-900/10 z-10">
          
          {/* Header Toggle bar */}
          <div className="bg-slate-50 border-b border-slate-200 px-4 py-2.5 flex justify-between items-center shrink-0 select-none">
            <div className="flex bg-slate-200/60 p-1 rounded-lg">
              <button
                onClick={() => setRightTab("chat")}
                className={`flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-semibold transition cursor-pointer ${
                  rightTab === "chat"
                    ? "bg-white text-slate-800 shadow-xs"
                    : "text-slate-500 hover:text-slate-700"
                }`}
                id="tab-toggle-chat"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                AI Chat
              </button>
              <button
                onClick={() => setRightTab("guide")}
                className={`flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-semibold transition cursor-pointer ${
                  rightTab === "guide"
                    ? "bg-white text-slate-800 shadow-xs"
                    : "text-slate-500 hover:text-slate-700"
                }`}
                id="tab-toggle-guide"
              >
                <Compass className="w-3.5 h-3.5" />
                Notebook Guide
              </button>
            </div>

            <span className="text-[10px] font-bold text-indigo-600 flex items-center gap-1">
              <Sparkles className="w-3.5 h-3.5 animate-pulse" />
              Gemini 3.5
            </span>
          </div>

          {/* Right Main Viewport */}
          <div className="flex-1 overflow-hidden">
            <AnimatePresence mode="wait">
              {rightTab === "chat" ? (
                <motion.div
                  key="chat"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="h-full"
                >
                  <ChatPanel
                    messages={messages}
                    sources={sources}
                    selectedSourceIds={selectedSourceIds}
                    onSendMessage={handleSendMessage}
                    onSelectSource={handleSelectSource}
                    onSaveResponseAsNote={handleSaveResponseAsNote}
                    isLoading={isLoadingChat}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="guide"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="h-full"
                >
                  <NotebookGuide
                    sources={sources}
                    selectedSourceIds={selectedSourceIds}
                    onAddNote={handleAddNote}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </section>

      </div>
    </div>
  );
}
