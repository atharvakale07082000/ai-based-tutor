/**
 * Single source of truth for user-facing agent and model display names.
 * Never render internal keys (doubt, quiz, DOUBT_SOLVER, etc.) directly to users.
 */

export const AGENT_DISPLAY_NAMES: Record<string, string> = {
  doubt: "Learning Assistant",
  quiz: "Quiz Creator",
  curriculum: "Learning Path Builder",
  progress: "Progress Tracker",
  assistant: "AI Tutor",
};

export const MODEL_DISPLAY_NAMES: Record<string, string> = {
  DOUBT_SOLVER: "Language Model",
  QUIZ_GENERATOR: "Language Model",
  TOPIC_CLASSIFIER: "Topic Classifier",
  DIFFICULTY_SCORER: "Difficulty Scorer",
  EMBEDDINGS: "Semantic Search",
  SPEECH_TO_TEXT: "Speech Recognition",
  SENTIMENT: "Sentiment Analysis",
  IMAGE_CAPTIONER: "Image Understanding",
  RECOMMENDATION_AGENT: "Recommendation Engine",
  SPACED_REPETITION: "Study Scheduler",
};

export function getAgentDisplayName(agentKey: string): string {
  return AGENT_DISPLAY_NAMES[agentKey] ?? "AI Tutor";
}

export function getModelDisplayName(modelKey: string): string {
  return MODEL_DISPLAY_NAMES[modelKey] ?? "AI Model";
}
