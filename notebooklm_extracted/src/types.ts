export interface Source {
  id: string;
  title: string;
  content: string;
  type: 'text' | 'url' | 'sample';
  url?: string;
  wordCount: number;
}

export interface Note {
  id: string;
  title: string;
  content: string;
  createdAt: string;
  sourceId?: string;
  sourceTitle?: string;
  color?: string; // Hex or tailwind class for sticky notes
}

export interface Message {
  id: string;
  role: 'user' | 'model';
  content: string;
  timestamp: string;
  citations?: string[]; // Extracted citations
}

export interface FAQItem {
  question: string;
  answer: string;
}

export interface KeyTerm {
  term: string;
  definition: string;
}

export interface QuizQuestion {
  question: string;
  options: string[];
  correctIndex: number;
  explanation: string;
}

export interface StudyGuide {
  keyTerms: KeyTerm[];
  quiz: QuizQuestion[];
  essayPrompt: string;
}

export interface TimelineEvent {
  date: string;
  title: string;
  description: string;
}

export interface BriefingDoc {
  executiveSummary: string;
  keyThemes: {
    theme: string;
    description: string;
  }[];
  keyTakeaways: string[];
}

export interface PodcastLine {
  speaker: 'Lucas' | 'Elena';
  text: string;
  emotion: string;
}
