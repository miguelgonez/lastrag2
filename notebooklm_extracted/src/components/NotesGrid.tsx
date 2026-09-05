import React, { useState } from "react";
import { Note } from "../types";
import { Plus, Trash2, Edit2, Check, FileText, Palette } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

interface NotesGridProps {
  notes: Note[];
  onAddNote: (title: string, content: string, color?: string) => void;
  onUpdateNote: (id: string, updates: Partial<Note>) => void;
  onDeleteNote: (id: string) => void;
  onOpenSource: (sourceId: string) => void;
}

const NOTE_COLORS = [
  { id: "slate", bg: "bg-slate-50 border-slate-200", focus: "ring-slate-400" },
  { id: "amber", bg: "bg-amber-50 border-amber-200", focus: "ring-amber-400" },
  { id: "emerald", bg: "bg-emerald-50 border-emerald-200", focus: "ring-emerald-400" },
  { id: "sky", bg: "bg-sky-50 border-sky-200", focus: "ring-sky-400" },
  { id: "indigo", bg: "bg-indigo-50 border-indigo-200", focus: "ring-indigo-400" },
  { id: "rose", bg: "bg-rose-50 border-rose-200", focus: "ring-rose-400" },
];

export default function NotesGrid({
  notes,
  onAddNote,
  onUpdateNote,
  onDeleteNote,
  onOpenSource,
}: NotesGridProps) {
  const [isAdding, setIsAdding] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newColor, setNewColor] = useState("slate");

  // Editing notes state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newContent.trim()) return;
    onAddNote(newTitle.trim() || "Untitled Note", newContent, newColor);
    setNewTitle("");
    setNewContent("");
    setNewColor("slate");
    setIsAdding(false);
  };

  const handleStartEdit = (note: Note) => {
    setEditingId(note.id);
    setEditTitle(note.title);
    setEditContent(note.content);
  };

  const handleSaveEdit = (id: string) => {
    onUpdateNote(id, { title: editTitle, content: editContent });
    setEditingId(null);
  };

  const getBgClass = (colorId?: string) => {
    const matched = NOTE_COLORS.find((c) => c.id === colorId);
    return matched ? matched.bg : "bg-slate-50 border-slate-200";
  };

  return (
    <div className="flex flex-col h-full bg-slate-50" id="notes-dashboard-container">
      {/* Notes Header */}
      <div className="p-4 border-b border-slate-200 bg-white shadow-xs flex items-center justify-between sticky top-0 z-10">
        <div>
          <h2 className="font-semibold text-slate-800 text-lg">Saved Notes</h2>
          <p className="text-xs text-slate-500">
            Write notes, summarize insights, or read saved clips from your documents.
          </p>
        </div>
        <button
          onClick={() => setIsAdding(!isAdding)}
          className="flex items-center gap-1.5 py-1.5 px-3 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg transition shadow-xs cursor-pointer"
          id="btn-trigger-add-note"
        >
          <Plus className="w-4 h-4" />
          New Note
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Add Note Form Panel */}
        <AnimatePresence>
          {isAdding && (
            <motion.form
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              onSubmit={handleAddSubmit}
              className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm overflow-hidden space-y-3"
              id="create-note-form"
            >
              <div className="flex justify-between items-center">
                <input
                  type="text"
                  placeholder="Note Title (optional)"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="text-sm font-semibold p-1 border-b border-transparent focus:border-indigo-200 outline-hidden w-full text-slate-800 bg-transparent"
                  id="input-note-title"
                />
              </div>
              <textarea
                placeholder="Take a note, type an insight..."
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                className="text-xs p-2 border border-slate-100 rounded-lg w-full h-24 resize-none bg-slate-50 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
                required
                id="textarea-note-content"
              />

              <div className="flex items-center justify-between pt-1">
                {/* Color Selector */}
                <div className="flex items-center gap-1.5">
                  <Palette className="w-3.5 h-3.5 text-slate-400" />
                  <div className="flex gap-1" id="note-color-picker">
                    {NOTE_COLORS.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => setNewColor(c.id)}
                        className={`w-4 h-4 rounded-full border border-slate-300 transition shrink-0 ${
                          c.id === "slate" ? "bg-slate-100" : 
                          c.id === "amber" ? "bg-amber-100" : 
                          c.id === "emerald" ? "bg-emerald-100" : 
                          c.id === "sky" ? "bg-sky-100" : 
                          c.id === "indigo" ? "bg-indigo-100" : "bg-rose-100"
                        } ${newColor === c.id ? "scale-125 ring-2 ring-indigo-500 ring-offset-1" : "hover:scale-110"}`}
                      />
                    ))}
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setIsAdding(false)}
                    className="px-2.5 py-1 text-slate-500 hover:text-slate-700 text-xs font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-md shadow-xs"
                    id="btn-submit-note"
                  >
                    Add
                  </button>
                </div>
              </div>
            </motion.form>
          )}
        </AnimatePresence>

        {/* Notes Grid */}
        {notes.length === 0 ? (
          <div className="text-center py-20 bg-white/50 rounded-2xl border border-dashed border-slate-200">
            <BookmarkPlaceholder />
            <h3 className="mt-4 font-semibold text-slate-700 text-sm">No notes saved</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-xs mx-auto">
              Add your custom notes or highlight source text inside the document reader to save them as sticky clips!
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <AnimatePresence>
              {notes.map((note) => {
                const isEditing = editingId === note.id;
                return (
                  <motion.div
                    key={note.id}
                    layout
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className={`p-4 rounded-xl border flex flex-col justify-between shadow-xs transition duration-150 relative group ${getBgClass(
                      note.color
                    )}`}
                    id={`note-card-${note.id}`}
                  >
                    <div>
                      {/* Note Title */}
                      {isEditing ? (
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="font-semibold text-slate-800 text-sm border-b border-indigo-300 bg-transparent outline-hidden w-full pb-1 mb-2"
                        />
                      ) : (
                        <h3 className="font-semibold text-slate-800 text-sm mb-2 pr-6">
                          {note.title}
                        </h3>
                      )}

                      {/* Note Content */}
                      {isEditing ? (
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          className="text-xs text-slate-700 bg-transparent outline-hidden w-full h-20 resize-none border border-indigo-100 rounded p-1"
                        />
                      ) : (
                        <p className="text-xs text-slate-700 leading-relaxed whitespace-pre-line break-words">
                          {note.content}
                        </p>
                      )}
                    </div>

                    {/* Footer with actions & metadata */}
                    <div className="mt-4 pt-3 border-t border-slate-200/50 flex flex-col gap-2">
                      {/* Document connection tag */}
                      {note.sourceTitle && note.sourceId && (
                        <button
                          onClick={() => onOpenSource(note.sourceId!)}
                          className="self-start inline-flex items-center gap-1 text-[10px] font-medium text-indigo-700 hover:text-indigo-900 bg-indigo-100/60 hover:bg-indigo-100 px-1.5 py-0.5 rounded transition cursor-pointer max-w-full truncate"
                          title={`Click to open source: ${note.sourceTitle}`}
                          id={`note-source-link-${note.id}`}
                        >
                          <FileText className="w-2.5 h-2.5 shrink-0" />
                          <span className="truncate">{note.sourceTitle}</span>
                        </button>
                      )}

                      <div className="flex items-center justify-between text-[10px] text-slate-400">
                        <span>{new Date(note.createdAt).toLocaleDateString()}</span>
                        
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition duration-150">
                          {isEditing ? (
                            <button
                              onClick={() => handleSaveEdit(note.id)}
                              className="p-1 hover:bg-slate-200 rounded-md text-emerald-600 transition"
                              title="Save Edit"
                              id={`btn-save-note-edit-${note.id}`}
                            >
                              <Check className="w-3.5 h-3.5" />
                            </button>
                          ) : (
                            <button
                              onClick={() => handleStartEdit(note)}
                              className="p-1 hover:bg-slate-200 rounded-md text-slate-500 hover:text-slate-700 transition"
                              title="Edit Note"
                              id={`btn-start-note-edit-${note.id}`}
                            >
                              <Edit2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            onClick={() => onDeleteNote(note.id)}
                            className="p-1 hover:bg-slate-200 rounded-md text-slate-400 hover:text-red-500 transition"
                            title="Delete Note"
                            id={`btn-delete-note-${note.id}`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}

function BookmarkPlaceholder() {
  return (
    <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto shadow-xs">
      <Bookmark className="w-6 h-6 animate-pulse" />
    </div>
  );
}

function Bookmark(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" />
    </svg>
  );
}
