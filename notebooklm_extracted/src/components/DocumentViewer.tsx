import React, { useState, useRef, useEffect } from "react";
import { Source } from "../types";
import { ArrowLeft, Plus, Highlighter, FileText, Bookmark } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

interface DocumentViewerProps {
  source: Source;
  onClose: () => void;
  onSaveSelectionAsNote: (text: string) => void;
}

export default function DocumentViewer({
  source,
  onClose,
  onSaveSelectionAsNote,
}: DocumentViewerProps) {
  const [selectedText, setSelectedText] = useState("");
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Watch text selection
  const handleTextSelection = () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) {
      setSelectedText("");
      setMenuPosition(null);
      return;
    }

    const text = selection.toString().trim();
    if (text.length > 0) {
      setSelectedText(text);

      // Position the selection menu above the highlighted text
      try {
        const range = selection.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        if (containerRef.current) {
          const containerRect = containerRef.current.getBoundingClientRect();
          // Calculate relative position to container
          setMenuPosition({
            x: rect.left - containerRect.left + (rect.width / 2),
            y: rect.top - containerRect.top - 40 + containerRef.current.scrollTop,
          });
        }
      } catch (e) {
        // Fallback positioning
        setMenuPosition(null);
      }
    }
  };

  useEffect(() => {
    const handleMouseUp = () => {
      // Delay slightly to allow selection to register
      setTimeout(handleTextSelection, 10);
    };

    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  const handleSaveNote = () => {
    if (!selectedText) return;
    onSaveSelectionAsNote(selectedText);
    setSelectedText("");
    setMenuPosition(null);
    
    // Clear browser selection
    window.getSelection()?.removeAllRanges();
  };

  return (
    <div className="flex flex-col h-full bg-white relative" ref={containerRef} id="document-viewer-container">
      {/* Viewer Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-100 bg-white sticky top-0 z-10 shadow-xs">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-slate-100 rounded-lg text-slate-500 hover:text-slate-700 transition"
            id="btn-close-doc-viewer"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-1.5 text-xs text-indigo-600 font-medium mb-0.5">
              <FileText className="w-3.5 h-3.5" />
              Source Reader
            </div>
            <h2 className="font-semibold text-slate-800 text-sm truncate max-w-sm sm:max-w-md md:max-w-lg lg:max-w-xl">
              {source.title}
            </h2>
          </div>
        </div>
        
        <div className="text-xs text-slate-400 font-mono">
          {source.wordCount} words
        </div>
      </div>

      {/* Floating Selection Tooltip */}
      <AnimatePresence>
        {menuPosition && selectedText && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 5 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 5 }}
            className="absolute z-30 bg-slate-900 text-white p-1 rounded-lg shadow-xl border border-slate-800 flex items-center gap-1 text-xs"
            style={{
              left: `${menuPosition.x}px`,
              top: `${menuPosition.y}px`,
              transform: "translateX(-50%)",
            }}
            id="text-selection-menu"
          >
            <button
              onClick={handleSaveNote}
              className="flex items-center gap-1 py-1 px-2.5 hover:bg-indigo-600 rounded-md transition font-medium cursor-pointer"
              id="btn-save-selection-to-notes"
            >
              <Bookmark className="w-3.5 h-3.5 text-indigo-300" />
              Save selection as Note
            </button>
            <span className="text-slate-700">|</span>
            <span className="px-2 text-slate-400 font-mono text-[10px]">
              {selectedText.split(/\s+/).length} words
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Document Content */}
      <div className="flex-1 overflow-y-auto p-6 sm:p-8 md:p-10" id="document-content-scroll">
        <article className="prose max-w-2xl mx-auto selection:bg-indigo-100 selection:text-indigo-900">
          <header className="mb-6 border-b border-slate-100 pb-4">
            <h1 className="text-2xl font-semibold text-slate-800 leading-tight">
              {source.title}
            </h1>
            {source.type === "url" && source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-indigo-500 hover:underline mt-2 inline-flex items-center gap-1"
              >
                Source: {source.url}
              </a>
            )}
          </header>

          <div className="text-slate-600 leading-relaxed space-y-4 text-sm md:text-base font-sans whitespace-pre-line">
            {source.content}
          </div>
        </article>
      </div>

      {/* Selector Tip Footer */}
      <div className="p-3 border-t border-slate-100 bg-slate-50 text-center text-xs text-slate-400 font-medium">
        <span className="inline-flex items-center gap-1">
          <Highlighter className="w-3.5 h-3.5 text-indigo-500" />
          Tip: Select any paragraph or sentence to save it instantly as a custom note!
        </span>
      </div>
    </div>
  );
}
