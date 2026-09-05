import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = 3000;

// Increase body parser limits for large documents
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ limit: "50mb", extended: true }));

// Shared Gemini client utility
const ai = new GoogleGenAI({
  apiKey: process.env.GEMINI_API_KEY || "",
  httpOptions: {
    headers: {
      'User-Agent': 'aistudio-build',
    }
  }
});

// Helper: Simple HTML text extraction
async function fetchAndExtractText(url: string): Promise<string> {
  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      }
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const html = await response.text();
    
    // Extract head title
    const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    const title = titleMatch ? titleMatch[1].trim() : "Scraped Page";

    // Extract body content or complete HTML if body is missing
    let content = html;
    const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
    if (bodyMatch) {
      content = bodyMatch[1];
    }

    // Strip style tags
    content = content.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "");
    // Strip script tags
    content = content.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "");
    // Strip HTML tags
    content = content.replace(/<[^>]+>/g, " ");
    // Normalize spaces
    content = content.replace(/\s+/g, " ").trim();

    // Limit text size to prevent token blowouts
    if (content.length > 50000) {
      content = content.substring(0, 50000) + "... [Content Truncated]";
    }

    return JSON.stringify({ title, text: content });
  } catch (error: any) {
    console.error("Scraping error:", error);
    throw new Error(error.message || "Failed to retrieve URL content");
  }
}

// Route: Scrape a URL
app.post("/api/scrape", async (req, res) => {
  const { url } = req.body;
  if (!url) {
    res.status(400).json({ error: "URL is required" });
    return;
  }
  try {
    const dataStr = await fetchAndExtractText(url);
    const data = JSON.parse(dataStr);
    res.json(data);
  } catch (error: any) {
    res.status(500).json({ error: error.message || "Failed to scrape URL" });
  }
});

// Route: Chat with sources
app.post("/api/gemini/chat", async (req, res) => {
  const { sources, messages, query } = req.body;

  if (!process.env.GEMINI_API_KEY) {
    res.status(500).json({ error: "Gemini API key is not configured. Please add it in Settings > Secrets." });
    return;
  }

  try {
    // Format sources into a readable block
    const sourcesBlock = sources && sources.length > 0
      ? sources.map((s: any, idx: number) => `--- DOCUMENT ${idx + 1}: ${s.title} ---\n${s.content}`).join("\n\n")
      : "No documents uploaded. Inform the user they can upload or select sources in the left panel.";

    const systemInstruction = `You are NotebookLM, a highly capable personalized AI collaborator. 
Your primary goal is to help the user synthesize, analyze, and learn from their uploaded documents (sources).

Here are the sources currently loaded in your context:
${sourcesBlock}

CRITICAL DIRECTIVES:
1. Ground all answers STRICTLY in the provided documents. If an answer cannot be found or reasonably inferred from the sources, clearly state that the provided sources do not contain this information. Do not use external pre-trained knowledge to answer things outside of these sources, unless explicitly asked to provide creative writing or external context.
2. CITATION RULE: When referencing information from a specific document, you MUST cite it using bracketed numbers like [Document Title] or [1] (where 1 is the document index/title). For example: "The spacecraft was launched in 1977 [Voyager Mission Overview]."
3. Keep your tone helpful, professional, engaging, and objective. Use elegant markdown to format your answers (bolding, lists, tables).
`;

    // Construct history for Gemini chat API
    // The chat history format should map roles: 'user' or 'model'
    // Let's filter or reconstruct previous messages
    const formattedContents = messages ? messages.map((m: any) => ({
      role: m.role === "user" ? "user" : "model",
      parts: [{ text: m.content }]
    })) : [];

    // Add current query
    formattedContents.push({
      role: "user",
      parts: [{ text: query }]
    });

    const response = await ai.models.generateContent({
      model: "gemini-3.5-flash",
      contents: formattedContents,
      config: {
        systemInstruction,
        temperature: 0.3, // Lower temperature for higher factual accuracy
      }
    });

    res.json({ text: response.text });
  } catch (error: any) {
    console.error("Gemini Chat Error:", error);
    res.status(500).json({ error: error.message || "Failed to generate AI response" });
  }
});

// Route: Generate Guide
app.post("/api/gemini/generate-guide", async (req, res) => {
  const { sources, guideType } = req.body;

  if (!process.env.GEMINI_API_KEY) {
    res.status(500).json({ error: "Gemini API key is not configured." });
    return;
  }

  if (!sources || sources.length === 0) {
    res.status(400).json({ error: "At least one source is required to generate a guide." });
    return;
  }

  try {
    const sourcesBlock = sources.map((s: any, idx: number) => `--- DOCUMENT ${idx + 1}: ${s.title} ---\n${s.content}`).join("\n\n");

    let prompt = "";
    let responseSchema: any = null;

    if (guideType === "faq") {
      prompt = `Based on the following documents, generate a highly informative, detailed FAQ. 
Produce a list of 5-8 frequently asked questions that someone reading these documents would have, along with extremely detailed answers grounded only in the text. Provide citations (e.g. [Document Title]) in the answers where relevant.`;
      
      responseSchema = {
        type: Type.ARRAY,
        description: "List of FAQs",
        items: {
          type: Type.OBJECT,
          properties: {
            question: { type: Type.STRING },
            answer: { type: Type.STRING, description: "Detailed answer with inline source citations" }
          },
          required: ["question", "answer"]
        }
      };
    } else if (guideType === "study-guide") {
      prompt = `Based on the following documents, generate a Study Guide. 
Extract 4-6 key concepts/terms with clear definitions, create 3-5 quiz questions (with options and the index of the correct answer, plus a brief explanation of why it is correct), and provide 1 thought-provoking essay/study prompt.`;
      
      responseSchema = {
        type: Type.OBJECT,
        properties: {
          keyTerms: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                term: { type: Type.STRING },
                definition: { type: Type.STRING }
              },
              required: ["term", "definition"]
            }
          },
          quiz: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                question: { type: Type.STRING },
                options: { type: Type.ARRAY, items: { type: Type.STRING } },
                correctIndex: { type: Type.INTEGER },
                explanation: { type: Type.STRING }
              },
              required: ["question", "options", "correctIndex", "explanation"]
            }
          },
          essayPrompt: { type: Type.STRING }
        },
        required: ["keyTerms", "quiz", "essayPrompt"]
      };
    } else if (guideType === "timeline") {
      prompt = `Based on the following documents, construct a Chronological Timeline of events.
Find all chronological dates, years, or milestones mentioned across the documents. Order them chronologically from oldest to newest. Provide at least 5-8 major milestones. Give each milestone a clear title, exact date/year, and a descriptive grounding of what happened.`;
      
      responseSchema = {
        type: Type.ARRAY,
        description: "List of timeline events ordered chronologically",
        items: {
          type: Type.OBJECT,
          properties: {
            date: { type: Type.STRING, description: "The specific date or year, e.g. '1977' or 'August 20, 1977'" },
            title: { type: Type.STRING, description: "Short title of the event" },
            description: { type: Type.STRING, description: "Ground description of what occurred" }
          },
          required: ["date", "title", "description"]
        }
      };
    } else {
      // Briefing Doc
      prompt = `Based on the following documents, generate a Briefing Document. 
Extract an overall Executive Summary (1-2 paragraphs), a list of 4-6 Key Themes (each with a summary description and concrete details), and 3-5 Recommended Action Items or Key Takeaways.`;

      responseSchema = {
        type: Type.OBJECT,
        properties: {
          executiveSummary: { type: Type.STRING },
          keyThemes: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                theme: { type: Type.STRING },
                description: { type: Type.STRING }
              },
              required: ["theme", "description"]
            }
          },
          keyTakeaways: {
            type: Type.ARRAY,
            items: { type: Type.STRING }
          }
        },
        required: ["executiveSummary", "keyThemes", "keyTakeaways"]
      };
    }

    const response = await ai.models.generateContent({
      model: "gemini-3.5-flash",
      contents: [
        { text: `SOURCES:\n${sourcesBlock}` },
        { text: prompt }
      ],
      config: {
        responseMimeType: "application/json",
        responseSchema,
        temperature: 0.2
      }
    });

    res.json(JSON.parse(response.text));
  } catch (error: any) {
    console.error("Generate Guide Error:", error);
    res.status(500).json({ error: error.message || "Failed to generate guide" });
  }
});

// Route: Generate Podcast script
app.post("/api/gemini/generate-podcast", async (req, res) => {
  const { sources } = req.body;

  if (!process.env.GEMINI_API_KEY) {
    res.status(500).json({ error: "Gemini API key is not configured." });
    return;
  }

  if (!sources || sources.length === 0) {
    res.status(400).json({ error: "At least one source is required." });
    return;
  }

  try {
    const sourcesBlock = sources.map((s: any, idx: number) => `--- DOCUMENT ${idx + 1}: ${s.title} ---\n${s.content}`).join("\n\n");

    const prompt = `You are a professional audio producer for NotebookLM.
Generate a highly engaging, conversational, and energetic podcast script summarizing and exploring the provided documents.
The hosts are:
- Lucas: An enthusiastic, curious, and expressive co-host. He loves summarizing things simply, asking great questions, and adding exciting color.
- Elena: A smart, analytical, and friendly co-host who loves deep diving into the facts, offering structured insights, and explaining complex ideas.

They should talk to each other in an incredibly natural way (using phrases like "Oh, absolutely!", "That's wild!", "Wait, let me wrap my head around that"). They should discuss the main themes, key dates, surprising findings, and core conclusions of the documents.
The dialogue must be structured as a conversational exchange with 12 to 18 lines. Keep it focused and impactful.

You must output a JSON array of script lines.`;

    const responseSchema = {
      type: Type.ARRAY,
      description: "Podcast dialogue lines",
      items: {
        type: Type.OBJECT,
        properties: {
          speaker: { type: Type.STRING, description: "Must be exactly 'Lucas' or 'Elena'" },
          text: { type: Type.STRING, description: "The spoken dialogue" },
          emotion: { type: Type.STRING, description: "Short emotion flag like 'excited', 'thoughtful', 'surprised', 'neutral', 'amused'" }
        },
        required: ["speaker", "text", "emotion"]
      }
    };

    const response = await ai.models.generateContent({
      model: "gemini-3.5-flash",
      contents: [
        { text: `SOURCES:\n${sourcesBlock}` },
        { text: prompt }
      ],
      config: {
        responseMimeType: "application/json",
        responseSchema,
        temperature: 0.7
      }
    });

    res.json(JSON.parse(response.text));
  } catch (error: any) {
    console.error("Podcast Generation Error:", error);
    res.status(500).json({ error: error.message || "Failed to generate podcast" });
  }
});

// Route: Generate Podcast Speech Audio segment
app.post("/api/gemini/generate-podcast-audio", async (req, res) => {
  const { lineText, speaker } = req.body;

  if (!process.env.GEMINI_API_KEY) {
    res.status(500).json({ error: "Gemini API key is not configured." });
    return;
  }

  if (!lineText) {
    res.status(400).json({ error: "lineText is required" });
    return;
  }

  try {
    // Map speaker to voice config
    // Zephyr: male-sounding (perfect for Lucas)
    // Puck: female-sounding (perfect for Elena)
    const voiceName = speaker === "Lucas" ? "Zephyr" : "Puck";

    const promptText = `Say this dialogue precisely as written: ${lineText}`;

    const response = await ai.models.generateContent({
      model: "gemini-3.1-flash-tts-preview",
      contents: [{ parts: [{ text: promptText }] }],
      config: {
        responseModalities: ['AUDIO'],
        speechConfig: {
          voiceConfig: {
            prebuiltVoiceConfig: { voiceName }
          }
        }
      }
    });

    const base64Audio = response.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
    if (base64Audio) {
      res.json({ audio: base64Audio });
    } else {
      res.status(500).json({ error: "No audio generated from the Gemini model" });
    }
  } catch (error: any) {
    console.error("TTS Generation Error:", error);
    res.status(500).json({ error: error.message || "Failed to synthesize speech" });
  }
});

// Serve static files in production
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
