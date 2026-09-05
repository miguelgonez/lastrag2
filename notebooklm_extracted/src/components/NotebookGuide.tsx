import React, { useState, useEffect, useRef } from "react";
import { Source, FAQItem, StudyGuide, TimelineEvent, BriefingDoc, PodcastLine } from "../types";
import {
  BookOpen,
  HelpCircle,
  Clock,
  Mic,
  Play,
  Pause,
  RotateCcw,
  Volume2,
  Sparkles,
  Award,
  BookMarked,
  Layers,
  ChevronDown,
  VolumeX,
  FastForward,
  Loader2,
  Bookmark
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

interface NotebookGuideProps {
  sources: Source[];
  selectedSourceIds: string[];
  onAddNote: (title: string, content: string, color?: string) => void;
}

type GuideTab = "briefing" | "faq" | "study" | "timeline" | "podcast";

export default function NotebookGuide({
  sources,
  selectedSourceIds,
  onAddNote,
}: NotebookGuideProps) {
  const [activeTab, setActiveTab] = useState<GuideTab>("briefing");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guide cache keyed by guideType + comma-separated selectedSourceIds
  const [cache, setCache] = useState<Record<string, any>>({});

  const activeSources = sources.filter((s) => selectedSourceIds.includes(s.id));
  const currentKey = selectedSourceIds.sort().join(",");

  const getCachedData = (type: GuideTab) => {
    return cache[`${type}-${currentKey}`];
  };

  const setCachedData = (type: GuideTab, data: any) => {
    setCache((prev) => ({
      ...prev,
      [`${type}-${currentKey}`]: data,
    }));
  };

  const handleGenerate = async (type: GuideTab) => {
    if (activeSources.length === 0) return;
    setIsLoading(true);
    setError(null);

    try {
      const endpoint = type === "podcast" ? "/api/gemini/generate-podcast" : "/api/gemini/generate-guide";
      const body = type === "podcast" 
        ? { sources: activeSources }
        : { sources: activeSources, guideType: type === "briefing" ? "briefing-doc" : type };

      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        throw new Error("Failed to generate guide content. Please try again.");
      }

      const data = await response.json();
      setCachedData(type, data);
    } catch (err: any) {
      console.error(err);
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white" id="notebook-guide-container">
      {/* Top Tabs */}
      <div className="flex border-b border-slate-200 overflow-x-auto bg-slate-50 shrink-0 select-none">
        {(
          [
            { id: "briefing", label: "Briefing", icon: BookOpen },
            { id: "faq", label: "FAQ", icon: HelpCircle },
            { id: "study", label: "Study Guide", icon: Award },
            { id: "timeline", label: "Timeline", icon: Clock },
            { id: "podcast", label: "Audio Overview", icon: Mic },
          ] as const
        ).map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                setError(null);
              }}
              className={`flex items-center gap-1.5 py-3 px-4 text-xs font-semibold border-b-2 transition shrink-0 cursor-pointer ${
                isActive
                  ? "border-indigo-600 text-indigo-600 bg-white"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100"
              }`}
              id={`tab-guide-${tab.id}`}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Main Guide Content */}
      <div className="flex-1 overflow-y-auto p-5" id="guide-content-scrollable">
        {activeSources.length === 0 ? (
          <div className="h-full flex flex-col justify-center items-center text-center p-6 space-y-4 max-w-sm mx-auto">
            <Layers className="w-10 h-10 text-slate-300 animate-pulse" />
            <div>
              <h3 className="font-semibold text-slate-700 text-sm">No sources active</h3>
              <p className="text-xs text-slate-500 mt-1">
                Select one or more documents in the left panel to generate summaries, study guides, and custom podcasts.
              </p>
            </div>
          </div>
        ) : (
          <AnimatePresence mode="wait">
            {isLoading ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full flex flex-col justify-center items-center text-center space-y-3 py-16"
              >
                <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
                <div>
                  <h4 className="font-semibold text-slate-800 text-sm">Generating Guide Workspace</h4>
                  <p className="text-xs text-slate-400 mt-1 max-w-xs mx-auto">
                    NotebookLM is analyzing your {activeSources.length} selected documents using Gemini...
                  </p>
                </div>
              </motion.div>
            ) : error ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-4 bg-red-50 border border-red-100 rounded-xl text-center space-y-3"
              >
                <p className="text-xs text-red-700 font-medium">{error}</p>
                <button
                  onClick={() => handleGenerate(activeTab)}
                  className="px-4 py-1.5 bg-red-600 text-white hover:bg-red-700 text-xs font-semibold rounded-lg shadow-xs"
                >
                  Retry Generation
                </button>
              </motion.div>
            ) : getCachedData(activeTab) ? (
              <motion.div
                key={`${activeTab}-content`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                {/* Heading indicator */}
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-1.5 text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                    <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
                    Gemini Synthesis Complete
                  </div>
                  <button
                    onClick={() => handleGenerate(activeTab)}
                    className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition"
                  >
                    Regenerate
                  </button>
                </div>

                {/* Tab Renderers */}
                {activeTab === "briefing" && (
                  <BriefingDocView
                    data={getCachedData("briefing")}
                    onAddNote={onAddNote}
                  />
                )}
                {activeTab === "faq" && (
                  <FAQView
                    faq={getCachedData("faq")}
                    onAddNote={onAddNote}
                  />
                )}
                {activeTab === "study" && (
                  <StudyGuideView
                    guide={getCachedData("study")}
                    onAddNote={onAddNote}
                  />
                )}
                {activeTab === "timeline" && (
                  <TimelineView
                    events={getCachedData("timeline")}
                    onAddNote={onAddNote}
                  />
                )}
                {activeTab === "podcast" && (
                  <PodcastView
                    script={getCachedData("podcast")}
                    onAddNote={onAddNote}
                  />
                )}
              </motion.div>
            ) : (
              <motion.div
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                className="h-full flex flex-col justify-center items-center text-center py-16 space-y-4 max-w-sm mx-auto"
              >
                <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center">
                  {activeTab === "briefing" ? <BookOpen className="w-6 h-6" /> :
                   activeTab === "faq" ? <HelpCircle className="w-6 h-6" /> :
                   activeTab === "study" ? <Award className="w-6 h-6" /> :
                   activeTab === "timeline" ? <Clock className="w-6 h-6" /> : <Mic className="w-6 h-6" />}
                </div>
                <div>
                  <h3 className="font-semibold text-slate-700 text-sm">
                    {activeTab === "briefing" && "Synthesize Briefing Document"}
                    {activeTab === "faq" && "Generate Interactive FAQ"}
                    {activeTab === "study" && "Create Custom Study Guide"}
                    {activeTab === "timeline" && "Build Chronological Timeline"}
                    {activeTab === "podcast" && "Host an Audio Podcast Overview"}
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    {activeTab === "briefing" && "Extract key themes, action items, and overall summary."}
                    {activeTab === "faq" && "Extract frequently asked questions with highly cited answers."}
                    {activeTab === "study" && "Extract major vocabulary terms, interactive quizzes, and essay prompts."}
                    {activeTab === "timeline" && "Organize historical events and chronological dates described in the text."}
                    {activeTab === "podcast" && "Generate a fully spoken interactive audio chat between Lucas & Elena."}
                  </p>
                </div>
                <button
                  onClick={() => handleGenerate(activeTab)}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-lg shadow-md transition shrink-0 cursor-pointer"
                  id={`btn-generate-guide-${activeTab}`}
                >
                  Generate Now
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

/* ========================================= */
/* SUB-RENDERER: Briefing Document */
/* ========================================= */
interface BriefingDocViewProps {
  data: BriefingDoc;
  onAddNote: (title: string, content: string, color?: string) => void;
}
function BriefingDocView({ data, onAddNote }: BriefingDocViewProps) {
  return (
    <div className="space-y-5" id="briefing-doc-view">
      {/* Executive Summary */}
      <div className="bg-slate-50 p-4 border border-slate-200/60 rounded-xl space-y-2">
        <div className="flex justify-between items-center">
          <h4 className="text-xs font-bold text-slate-700 tracking-wider uppercase">Executive Summary</h4>
          <button
            onClick={() => onAddNote("Executive Summary", data.executiveSummary, "sky")}
            className="text-[10px] text-indigo-600 font-semibold flex items-center gap-1 hover:underline cursor-pointer"
          >
            <Bookmark className="w-3 h-3" /> Save to Notes
          </button>
        </div>
        <p className="text-xs text-slate-600 leading-relaxed font-sans">{data.executiveSummary}</p>
      </div>

      {/* Key Themes */}
      <div className="space-y-2.5">
        <h4 className="text-xs font-bold text-slate-400 tracking-wider uppercase">Key Themes</h4>
        <div className="grid grid-cols-1 gap-3">
          {data.keyThemes.map((theme, idx) => (
            <div key={idx} className="bg-white p-3.5 border border-slate-150 rounded-xl space-y-1.5 shadow-xs relative group">
              <div className="flex justify-between items-center">
                <h5 className="text-xs font-semibold text-slate-800">{theme.theme}</h5>
                <button
                  onClick={() => onAddNote(`Theme: ${theme.theme}`, theme.description, "emerald")}
                  className="opacity-0 group-hover:opacity-100 text-[10px] text-indigo-600 font-semibold flex items-center gap-0.5 hover:underline transition"
                >
                  <Bookmark className="w-2.5 h-2.5" /> Save
                </button>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">{theme.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Recommended Action Items / Key Takeaways */}
      <div className="space-y-2.5">
        <h4 className="text-xs font-bold text-slate-400 tracking-wider uppercase">Key Takeaways</h4>
        <ul className="space-y-2">
          {data.keyTakeaways.map((takeaway, idx) => (
            <li key={idx} className="flex gap-2 text-xs text-slate-600 items-start">
              <span className="w-5 h-5 bg-indigo-50 text-indigo-600 rounded-full font-bold flex items-center justify-center text-[10px] shrink-0 mt-0.5">
                {idx + 1}
              </span>
              <span className="leading-relaxed mt-0.5">{takeaway}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ========================================= */
/* SUB-RENDERER: FAQ Accordion */
/* ========================================= */
interface FAQViewProps {
  faq: FAQItem[];
  onAddNote: (title: string, content: string, color?: string) => void;
}
function FAQView({ faq, onAddNote }: FAQViewProps) {
  const [openIdx, setOpenIdx] = useState<number | null>(0);

  return (
    <div className="space-y-3" id="faq-view">
      {faq.map((item, idx) => {
        const isOpen = openIdx === idx;
        return (
          <div key={idx} className="border border-slate-200 rounded-xl overflow-hidden shadow-xs">
            <button
              onClick={() => setOpenIdx(isOpen ? null : idx)}
              className="w-full flex justify-between items-center p-3.5 bg-white hover:bg-slate-50 text-left font-medium text-slate-800 text-xs"
            >
              <span>{item.question}</span>
              <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>
            <AnimatePresence>
              {isOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="bg-slate-50 p-4 border-t border-slate-100 overflow-hidden space-y-3"
                >
                  <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{item.answer}</p>
                  <div className="flex justify-end">
                    <button
                      onClick={() => onAddNote(`FAQ: ${item.question}`, item.answer, "amber")}
                      className="text-[10px] text-indigo-600 font-semibold flex items-center gap-1 hover:underline cursor-pointer"
                    >
                      <Bookmark className="w-3 h-3" /> Save this QA
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}

/* ========================================= */
/* SUB-RENDERER: Study Guide */
/* ========================================= */
interface StudyGuideViewProps {
  guide: StudyGuide;
  onAddNote: (title: string, content: string, color?: string) => void;
}
function StudyGuideView({ guide, onAddNote }: StudyGuideViewProps) {
  const [selectedAnswers, setSelectedAnswers] = useState<Record<number, number>>({});

  const handleSelectOption = (qIdx: number, oIdx: number) => {
    setSelectedAnswers((prev) => ({
      ...prev,
      [qIdx]: oIdx,
    }));
  };

  return (
    <div className="space-y-6" id="study-guide-view">
      {/* Key Terms */}
      <div className="space-y-3">
        <h4 className="text-xs font-bold text-slate-400 tracking-wider uppercase flex items-center gap-1">
          <BookMarked className="w-4 h-4 text-indigo-500" /> Key Vocabulary Terms
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {guide.keyTerms.map((term, idx) => (
            <div key={idx} className="bg-slate-50 border border-slate-150 p-3 rounded-xl space-y-1 group relative">
              <div className="flex justify-between items-center">
                <h5 className="text-xs font-semibold text-slate-800 font-mono">{term.term}</h5>
                <button
                  onClick={() => onAddNote(term.term, term.definition, "rose")}
                  className="opacity-0 group-hover:opacity-100 text-[10px] text-indigo-600 font-semibold flex items-center gap-0.5 hover:underline"
                >
                  <Bookmark className="w-2.5 h-2.5" /> Save
                </button>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">{term.definition}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Interactive Quiz */}
      <div className="space-y-4 pt-2">
        <h4 className="text-xs font-bold text-slate-400 tracking-wider uppercase">Interactive Quiz</h4>
        <div className="space-y-4">
          {guide.quiz.map((q, qIdx) => {
            const chosen = selectedAnswers[qIdx];
            const isAnswered = chosen !== undefined;
            return (
              <div key={qIdx} className="bg-white p-4 border border-slate-200 rounded-xl space-y-3 shadow-xs">
                <h5 className="text-xs font-semibold text-slate-800 leading-relaxed">
                  <span className="font-mono text-indigo-500 mr-1.5">Q{qIdx + 1}.</span>
                  {q.question}
                </h5>

                <div className="grid grid-cols-1 gap-2">
                  {q.options.map((opt, oIdx) => {
                    const isSelected = chosen === oIdx;
                    const isCorrect = q.correctIndex === oIdx;
                    let btnClass = "bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-600";
                    
                    if (isAnswered) {
                      if (isSelected) {
                        btnClass = isCorrect
                          ? "bg-emerald-50 border-emerald-300 text-emerald-800"
                          : "bg-red-50 border-red-300 text-red-800";
                      } else if (isCorrect) {
                        btnClass = "bg-emerald-50 border-emerald-300 text-emerald-800";
                      } else {
                        btnClass = "bg-slate-50/50 border-slate-100 text-slate-400 opacity-60";
                      }
                    }

                    return (
                      <button
                        key={oIdx}
                        disabled={isAnswered}
                        onClick={() => handleSelectOption(qIdx, oIdx)}
                        className={`w-full text-left p-2.5 rounded-lg border text-xs font-medium transition cursor-pointer ${btnClass}`}
                      >
                        {opt}
                      </button>
                    );
                  })}
                </div>

                {isAnswered && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    className="p-3 bg-indigo-50/40 border border-indigo-100/50 rounded-lg text-xs leading-relaxed"
                  >
                    <div className="flex justify-between items-center mb-1">
                      <span className={`font-semibold ${chosen === q.correctIndex ? "text-emerald-700" : "text-red-700"}`}>
                        {chosen === q.correctIndex ? "✓ Correct!" : "✗ Incorrect"}
                      </span>
                      <button
                        onClick={() => onAddNote(`Quiz Question: Q${qIdx + 1}`, `${q.question}\n\nCorrect Answer: ${q.options[q.correctIndex]}\n\nExplanation: ${q.explanation}`, "slate")}
                        className="text-[9px] text-indigo-600 font-bold hover:underline flex items-center gap-0.5"
                      >
                        <Bookmark className="w-2.5 h-2.5" /> Save
                      </button>
                    </div>
                    <p className="text-slate-600">{q.explanation}</p>
                  </motion.div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Essay Prompt */}
      <div className="bg-indigo-50/50 p-4 border border-indigo-100 rounded-xl space-y-2">
        <div className="flex justify-between items-center">
          <h4 className="text-xs font-bold text-indigo-800 tracking-wider uppercase">Deep Discussion Prompt</h4>
          <button
            onClick={() => onAddNote("Essay Prompt", guide.essayPrompt, "indigo")}
            className="text-[10px] text-indigo-600 font-semibold flex items-center gap-1 hover:underline cursor-pointer"
          >
            <Bookmark className="w-3 h-3" /> Save Discussion
          </button>
        </div>
        <p className="text-xs text-indigo-950 font-medium italic leading-relaxed">
          "{guide.essayPrompt}"
        </p>
      </div>
    </div>
  );
}

/* ========================================= */
/* SUB-RENDERER: Chronological Timeline */
/* ========================================= */
interface TimelineViewProps {
  events: TimelineEvent[];
  onAddNote: (title: string, content: string, color?: string) => void;
}
function TimelineView({ events, onAddNote }: TimelineViewProps) {
  // Order events chronologically just in case
  const sorted = [...events];

  return (
    <div className="relative pl-6 space-y-6" id="timeline-view">
      {/* Vertical Line */}
      <div className="absolute left-[11px] top-2 bottom-2 w-0.5 bg-indigo-100" />

      {sorted.map((event, idx) => (
        <div key={idx} className="relative group" id={`timeline-milestone-${idx}`}>
          {/* Circular Indicator */}
          <div className="absolute -left-[20px] top-1.5 w-3 h-3 rounded-full border-2 border-indigo-500 bg-white group-hover:bg-indigo-500 transition shrink-0" />

          {/* Event Content card */}
          <div className="bg-white p-4 border border-slate-200/80 rounded-xl space-y-1.5 shadow-xs relative group">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold font-mono bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full shrink-0">
                {event.date}
              </span>
              <button
                onClick={() => onAddNote(`${event.date} - ${event.title}`, event.description, "slate")}
                className="opacity-0 group-hover:opacity-100 text-[10px] text-indigo-600 font-semibold flex items-center gap-0.5 hover:underline transition"
              >
                <Bookmark className="w-2.5 h-2.5" /> Save milestone
              </button>
            </div>
            <h5 className="text-xs font-semibold text-slate-800">{event.title}</h5>
            <p className="text-xs text-slate-500 leading-relaxed">{event.description}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ========================================= */
/* SUB-RENDERER: Audio Podcast Overview */
/* ========================================= */
interface PodcastViewProps {
  script: PodcastLine[];
  onAddNote: (title: string, content: string, color?: string) => void;
}
function PodcastView({ script, onAddNote }: PodcastViewProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentLineIdx, setCurrentLineIdx] = useState<number>(-1);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);
  const [isSynthesizingLine, setIsSynthesizingLine] = useState<string | null>(null);

  // Web Speech synthesis ref
  const currentUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Audio HTML elements ref (for real gemini TTS audio)
  const [geminiAudioUrl, setGeminiAudioUrl] = useState<string | null>(null);
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);

  // Clean up speech synthesis when unmounted
  useEffect(() => {
    return () => {
      window.speechSynthesis.cancel();
    };
  }, []);

  const handleTogglePlay = () => {
    if (isPlaying) {
      // Pause
      window.speechSynthesis.pause();
      if (audioPlayerRef.current) audioPlayerRef.current.pause();
      setIsPlaying(false);
    } else {
      // Resume or Start fresh
      setIsPlaying(true);
      if (audioPlayerRef.current && geminiAudioUrl) {
        audioPlayerRef.current.play();
        return;
      }

      if (window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
      } else {
        // Start from beginning or next line
        const startIdx = currentLineIdx === -1 || currentLineIdx >= script.length - 1 ? 0 : currentLineIdx;
        speakLine(startIdx);
      }
    }
  };

  const handleStop = () => {
    window.speechSynthesis.cancel();
    if (audioPlayerRef.current) {
      audioPlayerRef.current.pause();
      audioPlayerRef.current.currentTime = 0;
    }
    setIsPlaying(false);
    setCurrentLineIdx(-1);
    setGeminiAudioUrl(null);
  };

  const speakLine = (index: number) => {
    if (index >= script.length) {
      setIsPlaying(false);
      setCurrentLineIdx(-1);
      return;
    }

    setCurrentLineIdx(index);
    const line = script[index];

    // Create browser speech synthesis
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(line.text);
    currentUtteranceRef.current = utterance;

    // Set voice configuration
    const voices = window.speechSynthesis.getVoices();
    
    // Choose voices:
    // Lucas: Male-sounding
    // Elena: Female-sounding
    if (line.speaker === "Lucas") {
      const maleVoice = voices.find(v => v.name.toLowerCase().includes("male") || v.name.toLowerCase().includes("david") || v.name.toLowerCase().includes("google us english"));
      if (maleVoice) utterance.voice = maleVoice;
      utterance.pitch = 0.9;
      utterance.rate = 1.05 * playbackSpeed;
    } else {
      const femaleVoice = voices.find(v => v.name.toLowerCase().includes("female") || v.name.toLowerCase().includes("zira") || v.name.toLowerCase().includes("google uk english female"));
      if (femaleVoice) utterance.voice = femaleVoice;
      utterance.pitch = 1.1;
      utterance.rate = 1.0 * playbackSpeed;
    }

    utterance.onend = () => {
      // Speak next line automatically
      if (isPlaying) {
        speakLine(index + 1);
      }
    };

    utterance.onerror = () => {
      setIsPlaying(false);
    };

    window.speechSynthesis.speak(utterance);
  };

  // Listen to speed changes and apply them dynamically
  useEffect(() => {
    if (isPlaying && currentLineIdx !== -1 && currentUtteranceRef.current) {
      // Re-trigger current sentence to apply speed immediately
      speakLine(currentLineIdx);
    }
  }, [playbackSpeed]);

  // Request authentic Gemini TTS spoken audio for a specific line
  const handleHearAuthenticVoice = async (line: PodcastLine, index: number) => {
    setIsSynthesizingLine(line.text);
    window.speechSynthesis.cancel();
    setIsPlaying(false);

    try {
      const response = await fetch("/api/gemini/generate-podcast-audio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lineText: line.text, speaker: line.speaker }),
      });

      if (!response.ok) throw new Error();

      const data = await response.json();
      if (data.audio) {
        const audioBlob = base64ToBlob(data.audio, "audio/wav");
        const audioUrl = URL.createObjectURL(audioBlob);
        setGeminiAudioUrl(audioUrl);
        setCurrentLineIdx(index);
        
        // Wait for next render cycle for element reference to bind
        setTimeout(() => {
          if (audioPlayerRef.current) {
            audioPlayerRef.current.play();
            setIsPlaying(true);
          }
        }, 100);
      }
    } catch (err) {
      console.error(err);
      alert("Authentic Gemini TTS voice generation timed out. Falling back to default speech synthesis.");
    } finally {
      setIsSynthesizingLine(null);
    }
  };

  const base64ToBlob = (base64: string, mimeType: string) => {
    const byteCharacters = atob(base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    return new Blob([byteArray], { type: mimeType });
  };

  return (
    <div className="space-y-5" id="podcast-dashboard-container">
      {/* Audio player dashboard (Sleek Interface style) */}
      <div className="bg-indigo-600 text-white rounded-2xl p-6 shadow-xl shadow-indigo-600/15 border border-indigo-500/30 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center text-white">
              <Mic className="w-4 h-4 animate-pulse" />
            </div>
            <div>
              <h4 className="text-sm font-bold">Lucas & Elena Show</h4>
              <p className="text-[10px] text-indigo-150">Grounded Synthesis Podcast</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <Volume2 className="w-3.5 h-3.5 text-indigo-200" />
            <span className="text-[9px] font-bold text-indigo-100 uppercase tracking-widest font-mono">AUDIO OVERVIEW</span>
          </div>
        </div>

        {/* Waves display during play */}
        <div className="bg-white/10 rounded-xl p-3 flex items-center justify-center h-14 relative overflow-hidden border border-white/10">
          {isPlaying ? (
            <div className="flex gap-1.5 items-end h-8">
              {[...Array(14)].map((_, i) => (
                <span
                  key={i}
                  className="w-1 bg-white rounded-full animate-bounce"
                  style={{
                    height: `${Math.random() * 24 + 4}px`,
                    animationDuration: `${Math.random() * 500 + 400}ms`,
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="w-full h-0.5 bg-white/20 relative">
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-indigo-600 border border-white/10 px-3.5 py-0.5 rounded-full text-[9px] text-white/90 font-mono tracking-wider uppercase">
                Player Idle
              </div>
            </div>
          )}
        </div>

        {/* Player controls */}
        <div className="flex items-center justify-between pt-1">
          {/* Speed control */}
          <button
            onClick={() => setPlaybackSpeed(prev => prev === 1 ? 1.25 : prev === 1.25 ? 1.5 : 1)}
            className="flex items-center gap-1 py-1.5 px-3 bg-white/10 hover:bg-white/20 text-[10px] font-mono font-bold rounded-lg transition-colors cursor-pointer"
            title="Adjust reading speed"
          >
            <FastForward className="w-3 h-3" />
            {playbackSpeed}x Speed
          </button>

          {/* Core play actions */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleStop}
              className="p-2.5 bg-white/10 hover:bg-white/20 text-white rounded-full transition-colors cursor-pointer"
              title="Stop Podcast"
              id="btn-stop-podcast"
            >
              <RotateCcw className="w-4 h-4" />
            </button>

            <button
              onClick={handleTogglePlay}
              className="p-4 bg-white text-indigo-600 hover:bg-slate-50 rounded-full transition-all shadow-md shadow-indigo-900/10 cursor-pointer"
              title={isPlaying ? "Pause" : "Play Overview"}
              id="btn-play-pause-podcast"
            >
              {isPlaying ? <Pause className="w-5 h-5 fill-indigo-600" /> : <Play className="w-5 h-5 fill-indigo-600 ml-0.5" />}
            </button>
          </div>

          <span className="text-[10px] text-indigo-150 font-mono bg-white/5 px-2.5 py-1 rounded-md border border-white/5">
            {currentLineIdx === -1 ? "0" : currentLineIdx + 1}/{script.length} lines
          </span>
        </div>

        {/* Hidden Audio element for real Gemini synthesis */}
        {geminiAudioUrl && (
          <audio
            ref={audioPlayerRef}
            src={geminiAudioUrl}
            onEnded={() => {
              setIsPlaying(false);
              setGeminiAudioUrl(null);
            }}
          />
        )}
      </div>

      {/* Synchronized Script Lines */}
      <div className="space-y-4">
        <h4 className="text-xs font-bold text-slate-400 tracking-wider uppercase">Transcript Script</h4>
        <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
          {script.map((line, idx) => {
            const isLucas = line.speaker === "Lucas";
            const isActive = currentLineIdx === idx;
            
            return (
              <div
                key={idx}
                className={`flex gap-3 p-3 rounded-xl border transition duration-250 ${
                  isActive
                    ? "bg-indigo-50 border-indigo-200 shadow-xs scale-[1.01]"
                    : "bg-white border-slate-150"
                }`}
                id={`podcast-line-${idx}`}
              >
                {/* Speaker indicator */}
                <div className="shrink-0 flex flex-col items-center">
                  <div
                    className={`w-9 h-9 rounded-full font-bold text-xs flex items-center justify-center uppercase ${
                      isLucas
                        ? "bg-sky-100 text-sky-800 border border-sky-200"
                        : "bg-rose-100 text-rose-800 border border-rose-200"
                    }`}
                  >
                    {line.speaker[0]}
                  </div>
                  <span className="text-[9px] font-mono font-semibold text-slate-400 mt-1 uppercase">
                    {line.speaker}
                  </span>
                </div>

                {/* Line text */}
                <div className="flex-1 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-indigo-500 capitalize italic font-serif">
                      Emotion: {line.emotion}
                    </span>

                    <div className="flex gap-1.5">
                      {/* Hear high-quality Gemini TTS voice */}
                      <button
                        onClick={() => handleHearAuthenticVoice(line, idx)}
                        disabled={isSynthesizingLine !== null}
                        className="text-[9px] font-bold text-slate-400 hover:text-indigo-600 border border-slate-200 hover:border-indigo-200 bg-slate-50 hover:bg-slate-100 px-1.5 py-0.5 rounded transition disabled:opacity-40"
                      >
                        {isSynthesizingLine === line.text ? (
                          <span className="flex items-center gap-0.5">
                            <Loader2 className="w-2.5 h-2.5 animate-spin" /> Synthesizing...
                          </span>
                        ) : (
                          "🗣 Hear Gemini Voice"
                        )}
                      </button>

                      <button
                        onClick={() => onAddNote(`Podcast Quote - ${line.speaker}`, `"${line.text}"`, isLucas ? "sky" : "rose")}
                        className="text-[9px] text-slate-400 hover:text-indigo-600 border border-slate-200 rounded px-1.5 py-0.5 hover:bg-slate-50"
                      >
                        Save Line
                      </button>
                    </div>
                  </div>

                  <p className="text-xs text-slate-700 leading-relaxed font-sans">{line.text}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
