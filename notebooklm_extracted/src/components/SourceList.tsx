import React, { useState } from "react";
import { Source } from "../types";
import { FileText, Link, Plus, Sparkles, Trash2, CheckCircle2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

interface SourceListProps {
  sources: Source[];
  selectedSourceIds: string[];
  activeSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
  onToggleSourceSelection: (sourceId: string) => void;
  onToggleAllSources: (selected: boolean) => void;
  onAddTextSource: (title: string, content: string) => void;
  onAddUrlSource: (url: string) => void;
  onDeleteSource: (sourceId: string) => void;
  isScraping: boolean;
}

export default function SourceList({
  sources,
  selectedSourceIds,
  activeSourceId,
  onSelectSource,
  onToggleSourceSelection,
  onToggleAllSources,
  onAddTextSource,
  onAddUrlSource,
  onDeleteSource,
  isScraping,
}: SourceListProps) {
  const [showAddText, setShowAddText] = useState(false);
  const [showAddUrl, setShowAddUrl] = useState(false);
  
  // Forms state
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [urlError, setUrlError] = useState("");

  const handleAddTextSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;
    onAddTextSource(newTitle, newContent);
    setNewTitle("");
    setNewContent("");
    setShowAddText(false);
  };

  const handleAddUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setUrlError("");
    if (!newUrl.trim()) return;
    if (!newUrl.startsWith("http://") && !newUrl.startsWith("https://")) {
      setUrlError("URL must start with http:// or https://");
      return;
    }
    onAddUrlSource(newUrl);
    setNewUrl("");
    setShowAddUrl(false);
  };

  const userSources = sources.filter((s) => s.type !== "sample");
  const sampleSources = sources.filter((s) => s.type === "sample");

  return (
    <div className="flex flex-col h-full bg-slate-50 border-r border-slate-200" id="sources-sidebar-container">
      {/* Title & Stats */}
      <div className="p-4 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-600 animate-pulse" />
            <h2 className="font-semibold text-slate-800 text-lg">Sources</h2>
          </div>
          <span className="text-xs font-mono font-medium bg-slate-100 text-slate-600 px-2 py-1 rounded-full">
            {selectedSourceIds.length} active
          </span>
        </div>
        <p className="text-xs text-slate-500">
          Toggle sources to include them in the AI's answering context.
        </p>

        {/* Global toggles */}
        {sources.length > 0 && (
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => onToggleAllSources(true)}
              className="text-xs font-medium text-indigo-600 hover:text-indigo-800 transition"
              id="btn-select-all-sources"
            >
              Select All
            </button>
            <span className="text-slate-300 text-xs">|</span>
            <button
              onClick={() => onToggleAllSources(false)}
              className="text-xs font-medium text-slate-600 hover:text-slate-800 transition"
              id="btn-deselect-all-sources"
            >
              Deselect All
            </button>
          </div>
        )}
      </div>

      {/* Buttons to add (Sleek Interface style) */}
      <div className="p-3 flex gap-2 border-b border-slate-100 bg-[#F9FAFB]">
        <button
          onClick={() => {
            setShowAddText(true);
            setShowAddUrl(false);
          }}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-xl border border-slate-200 hover:border-slate-300 transition-all shadow-xs cursor-pointer"
          id="btn-add-text-source"
        >
          <Plus className="w-3.5 h-3.5 text-indigo-600" />
          Add text
        </button>
        <button
          onClick={() => {
            setShowAddUrl(true);
            setShowAddText(false);
          }}
          disabled={isScraping}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-semibold rounded-xl border border-indigo-100 transition-all disabled:opacity-50 cursor-pointer"
          id="btn-add-url-source"
        >
          <Link className="w-3.5 h-3.5 text-indigo-600" />
          {isScraping ? "Fetching..." : "Add website"}
        </button>
      </div>

      {/* Modal/Form Inputs inline */}
      <AnimatePresence>
        {showAddText && (
          <motion.form
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            onSubmit={handleAddTextSubmit}
            className="p-4 bg-indigo-50/40 border-b border-indigo-100/60 overflow-hidden"
            id="add-text-form"
          >
            <h3 className="text-xs font-bold text-indigo-950 mb-2 uppercase tracking-wider">Create Text Document</h3>
            <input
              type="text"
              placeholder="Document Title (e.g. Lecture Notes)"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              className="w-full text-xs p-2.5 border border-slate-200 rounded-lg mb-2 bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
              required
              id="input-text-title"
            />
            <textarea
              placeholder="Paste or type document content here..."
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              className="w-full text-xs p-2.5 border border-slate-200 rounded-lg mb-2 h-28 resize-none bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
              required
              id="textarea-text-content"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAddText(false)}
                className="px-2.5 py-1 text-slate-500 hover:text-slate-800 text-xs font-medium cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-lg shadow-sm cursor-pointer"
                id="btn-submit-text-source"
              >
                Add Document
              </button>
            </div>
          </motion.form>
        )}

        {showAddUrl && (
          <motion.form
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            onSubmit={handleAddUrlSubmit}
            className="p-4 bg-emerald-50/40 border-b border-emerald-100/60 overflow-hidden"
            id="add-url-form"
          >
            <h3 className="text-xs font-bold text-emerald-950 mb-2 uppercase tracking-wider">Import from URL</h3>
            <p className="text-[10px] text-slate-500 mb-2 leading-relaxed">
              Enter a web page URL. The server will extract and summarize the readable article text.
            </p>
            <input
              type="url"
              placeholder="https://example.com/article"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              className="w-full text-xs p-2.5 border border-slate-200 rounded-lg mb-1 bg-white focus:outline-hidden focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition-all"
              required
              id="input-url-path"
            />
            {urlError && <p className="text-[10px] text-red-500 mb-2">{urlError}</p>}
            <div className="flex justify-end gap-2 mt-2">
              <button
                type="button"
                onClick={() => setShowAddUrl(false)}
                className="px-2.5 py-1 text-slate-500 hover:text-slate-800 text-xs font-medium cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isScraping}
                className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-lg shadow-sm disabled:opacity-50 cursor-pointer"
                id="btn-submit-url-source"
              >
                {isScraping ? "Fetching..." : "Fetch Content"}
              </button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>

      {/* List of sources */}
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* User Documents */}
        <div>
          <div className="text-[10px] font-bold text-slate-400 tracking-wider uppercase mb-2 px-1">
            Your Documents ({userSources.length})
          </div>
          {userSources.length === 0 ? (
            <div className="text-center py-6 px-4 bg-white rounded-xl border border-dashed border-slate-200">
              <p className="text-xs text-slate-400">No custom documents yet.</p>
              <p className="text-[10px] text-slate-400 mt-1">Add text or import from links above.</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {userSources.map((source) => {
                const isSelected = selectedSourceIds.includes(source.id);
                const isActive = activeSourceId === source.id;
                const formatLabel = source.type === "url" ? "link" : "text";

                return (
                  <motion.div
                    key={source.id}
                    layoutId={`source-item-${source.id}`}
                    className={`group flex items-center gap-3 p-2.5 rounded-xl border text-left transition-all ${
                      isActive
                        ? "bg-indigo-50 border-indigo-100"
                        : "bg-white hover:bg-slate-50 border-slate-200/80"
                    }`}
                    id={`source-item-${source.id}`}
                  >
                    {/* Checkbox */}
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleSourceSelection(source.id)}
                      className="rounded text-indigo-600 border-slate-300 focus:ring-indigo-500 w-3.5 h-3.5 cursor-pointer shrink-0"
                      id={`checkbox-source-${source.id}`}
                    />

                    {/* Source Icon, Label & Title */}
                    <button
                      onClick={() => onSelectSource(source.id)}
                      className="flex-1 flex items-center gap-3 text-left overflow-hidden cursor-pointer"
                    >
                      {/* Modern uppercase tag label */}
                      <div className={`py-1 px-1.5 rounded font-mono text-[9px] uppercase font-bold shrink-0 shadow-xs border ${
                        isActive
                          ? "bg-white text-indigo-600 border-indigo-100"
                          : "bg-slate-100 text-slate-500 border-slate-200"
                      }`}>
                        {formatLabel}
                      </div>

                      <div className="truncate">
                        <div className={`text-xs truncate transition-colors ${
                          isActive ? "font-semibold text-indigo-950" : "font-medium text-slate-700"
                        }`}>
                          {source.title}
                        </div>
                        <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                          {source.wordCount} words
                        </div>
                      </div>
                    </button>

                    {/* Delete button */}
                    <button
                      onClick={() => onDeleteSource(source.id)}
                      className="opacity-0 group-hover:opacity-100 p-1 hover:bg-slate-100 rounded-md text-slate-400 hover:text-red-500 transition shrink-0"
                      title="Delete Source"
                      id={`btn-delete-source-${source.id}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>

        {/* Sample Documents */}
        <div>
          <div className="text-[10px] font-bold text-slate-400 tracking-wider uppercase mb-2 px-1">
            Sample Resources ({sampleSources.length})
          </div>
          <div className="space-y-1.5">
            {sampleSources.map((source) => {
              const isSelected = selectedSourceIds.includes(source.id);
              const isActive = activeSourceId === source.id;
              
              // Map sample types to elegant labels
              let formatLabel = "doc";
              if (source.id.includes("voyager")) formatLabel = "pdf";
              if (source.id.includes("coffee")) formatLabel = "doc";
              if (source.id.includes("vite")) formatLabel = "link";

              return (
                <div
                  key={source.id}
                  className={`group flex items-center gap-3 p-2.5 rounded-xl border text-left transition-all ${
                    isActive
                      ? "bg-indigo-50 border-indigo-100"
                      : "bg-white hover:bg-slate-50 border-slate-200/80"
                  }`}
                  id={`source-item-${source.id}`}
                >
                  {/* Checkbox */}
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleSourceSelection(source.id)}
                    className="rounded text-indigo-600 border-slate-300 focus:ring-indigo-500 w-3.5 h-3.5 cursor-pointer shrink-0"
                    id={`checkbox-source-${source.id}`}
                  />

                  {/* Source Icon, Label & Title */}
                  <button
                    onClick={() => onSelectSource(source.id)}
                    className="flex-1 flex items-center gap-3 text-left overflow-hidden cursor-pointer"
                  >
                    {/* Modern uppercase tag label */}
                    <div className={`py-1 px-1.5 rounded font-mono text-[9px] uppercase font-bold shrink-0 shadow-xs border ${
                      isActive
                        ? "bg-white text-indigo-600 border-indigo-100"
                        : "bg-slate-100 text-slate-500 border-slate-200"
                    }`}>
                      {formatLabel}
                    </div>

                    <div className="truncate">
                      <div className={`text-xs truncate transition-colors ${
                        isActive ? "font-semibold text-indigo-950" : "font-medium text-slate-700"
                      }`}>
                        {source.title}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                        {source.wordCount} words
                      </div>
                    </div>
                  </button>
                  
                  {/* Checkmark indicator */}
                  {isSelected && (
                    <CheckCircle2 className="w-3.5 h-3.5 text-indigo-600 ml-1 shrink-0" />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
