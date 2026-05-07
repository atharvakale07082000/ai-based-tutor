import { HfInference } from '@huggingface/inference'

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

let _hfClient: HfInference | null = null

export function getHFClient(): HfInference {
  if (!_hfClient) {
    const token = import.meta.env.VITE_HF_TOKEN
    if (!token || token === 'hf_placeholder_replace_with_real_token') {
      console.warn('[HF] No real HF token set — inference calls will fail. Set VITE_HF_TOKEN in .env')
    }
    _hfClient = new HfInference(token)
  }
  return _hfClient
}

export interface HFTextGenerationInput {
  model: string
  inputs: string
  parameters?: {
    max_new_tokens?: number
    temperature?: number
    top_p?: number
    repetition_penalty?: number
    return_full_text?: boolean
  }
}

export interface HFZeroShotInput {
  model: string
  inputs: string
  parameters: {
    candidate_labels: string[]
    multi_label?: boolean
  }
}

export interface HFSentimentOutput {
  label: string
  score: number
}

export interface HFZeroShotOutput {
  sequence: string
  labels: string[]
  scores: number[]
}

/** Run text generation (Mistral, Flan-T5) */
export async function runTextGeneration(
  modelKey: HFModelKey,
  prompt: string,
  params: HFTextGenerationInput['parameters'] = {}
): Promise<string> {
  const client = getHFClient()
  const modelId = HF_MODELS[modelKey]

  const result = await client.textGeneration({
    model: modelId,
    inputs: prompt,
    parameters: {
      max_new_tokens: 512,
      temperature: 0.7,
      return_full_text: false,
      ...params,
    },
  })

  return result.generated_text ?? ''
}

/** Run zero-shot classification (BART) */
export async function runZeroShot(
  inputs: string,
  candidateLabels: string[],
  multiLabel = false
): Promise<HFZeroShotOutput> {
  const client = getHFClient()

  const result = await client.zeroShotClassification({
    model: HF_MODELS.TOPIC_CLASSIFIER,
    inputs,
    parameters: {
      candidate_labels: candidateLabels,
      multi_label: multiLabel,
    },
  })

  // Handle array result from zeroShotClassification
  const item = Array.isArray(result) ? result[0] : result
  return item as HFZeroShotOutput
}

/** Run sentiment analysis (DistilBERT) */
export async function runSentiment(text: string): Promise<HFSentimentOutput[]> {
  const client = getHFClient()

  const result = await client.textClassification({
    model: HF_MODELS.SENTIMENT,
    inputs: text,
  })

  return result as HFSentimentOutput[]
}

/** Run feature extraction / embeddings */
export async function runEmbeddings(text: string): Promise<number[]> {
  const client = getHFClient()

  const result = await client.featureExtraction({
    model: HF_MODELS.EMBEDDINGS,
    inputs: text,
  })

  // The result can be nested arrays for sentence embeddings
  if (Array.isArray(result) && Array.isArray(result[0])) {
    return result[0] as number[]
  }
  return result as number[]
}

/** Run image captioning (BLIP) */
export async function runImageCaption(imageBlob: Blob): Promise<string> {
  const client = getHFClient()

  const result = await client.imageToText({
    model: HF_MODELS.IMAGE_CAPTIONER,
    data: imageBlob,
  })

  return result.generated_text ?? ''
}

/** Run automatic speech recognition (Whisper) */
export async function runSpeechToText(audioBlob: Blob): Promise<string> {
  const client = getHFClient()

  const result = await client.automaticSpeechRecognition({
    model: HF_MODELS.SPEECH_TO_TEXT,
    data: audioBlob,
  })

  return result.text ?? ''
}

/** Compute cosine similarity between two embedding vectors */
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
