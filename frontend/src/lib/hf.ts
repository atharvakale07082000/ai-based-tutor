// HuggingFace model registry (display/reference only).
//
// All AI inference now runs on the backend via the resilient generation client —
// the browser no longer calls HuggingFace directly, so there is no client-side HF
// token. `HF_MODELS` is kept for the Admin model-status panel and labels.

export const HF_MODELS = {
  DOUBT_SOLVER: 'mistralai/Mistral-7B-Instruct-v0.3',
  QUIZ_GENERATOR: 'google/flan-t5-large',
  TOPIC_CLASSIFIER: 'facebook/bart-large-mnli',
  DIFFICULTY_SCORER: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  EMBEDDINGS: 'sentence-transformers/all-MiniLM-L6-v2',
  SPEECH_TO_TEXT: 'openai/whisper-large-v3',
  SENTIMENT: 'distilbert/distilbert-base-uncased-finetuned-sst-2-english',
  IMAGE_CAPTIONER: 'Salesforce/blip-image-captioning-large',
} as const

export type HFModelKey = keyof typeof HF_MODELS

/** Compute cosine similarity between two embedding vectors. */
export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) return 0
  let dot = 0
  let normA = 0
  let normB = 0
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]
    normA += a[i] ** 2
    normB += b[i] ** 2
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB) + 1e-8)
}
