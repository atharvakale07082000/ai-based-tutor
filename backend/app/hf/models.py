HF_MODELS: dict[str, dict] = {
    # ── Generation tasks (provider: together) ────────────────────────────────
    "DOUBT_SOLVER": {
        "model_id": "Qwen/Qwen2.5-7B-Instruct",
        "task": "text-generation",
        "provider": "auto",
        "description": "Streaming doubt resolution chatbot (Qwen2.5-7B via HF auto-router)",
    },
    "QUIZ_GENERATOR": {
        "model_id": "Qwen/Qwen2.5-7B-Instruct",
        "task": "text-generation",
        "provider": "auto",
        "description": "Quiz question generation via Qwen2.5-7B-Instruct (HF auto-router)",
    },
    # ── Classification / embedding tasks (provider: hf-inference) ────────────
    "TOPIC_CLASSIFIER": {
        "model_id": "facebook/bart-large-mnli",
        "task": "zero-shot-classification",
        "provider": "hf-inference",
        "description": "Classify learner goals into topics",
    },
    "DIFFICULTY_SCORER": {
        "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "task": "text-classification",
        "provider": "hf-inference",
        "description": "Score content difficulty",
    },
    "EMBEDDINGS": {
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "task": "feature-extraction",
        "provider": "hf-inference",
        "description": "Semantic search embeddings",
    },
    "SPEECH_TO_TEXT": {
        "model_id": "openai/whisper-large-v3-turbo",
        "task": "automatic-speech-recognition",
        "provider": "hf-inference",
        "description": "Voice input transcription (upgraded: v3-turbo)",
    },
    "SENTIMENT": {
        "model_id": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
        "task": "text-classification",
        "provider": "hf-inference",
        "description": "Learner mood analysis",
    },
    "IMAGE_CAPTIONER": {
        "model_id": "Salesforce/blip-image-captioning-large",
        "task": "image-to-text",
        "provider": "hf-inference",
        "description": "Caption uploaded diagrams/images",
    },
}
