"""
Sentiment Classifier
─────────────────────
Primary model: cardiffnlp/twitter-roberta-base-sentiment-latest
  - Fine-tuned on 124M tweets
  - 3-class: negative / neutral / positive
  - Ideal for short social media text
  - Free, MIT-compatible
  - ~500MB, fits in 1GB RAM comfortably for batch inference
  - Rejected alternatives:
      distilbert-base-uncased-finetuned-sst-2-english → binary only, no neutral
      nlptown/bert-base-multilingual-uncased-sentiment → 5-star scale, overkill
      finiteautomata/bertweet-base-sentiment-analysis → similar quality, less maintained

Inference:
  - Loads once, stays in memory
  - Batch inference via transformers pipeline
  - Truncates to 128 tokens (social text is short; faster, lower memory)
  - Failures return None-scored with method=failed for alerting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config.settings import (
    CLASSIFIER_BATCH_SIZE,
    MODEL_CACHE_DIR,
    SENTIMENT_MODEL,
)

logger = logging.getLogger(__name__)

LABEL_MAP = {
    "LABEL_0": "negative",
    "LABEL_1": "neutral",
    "LABEL_2": "positive",
    # Some model checkpoints use these
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
}


@dataclass
class SentimentResult:
    label: Optional[str]  # positive|neutral|negative|None
    score: Optional[float]  # confidence for winning label
    raw_pos: Optional[float]
    raw_neu: Optional[float]
    raw_neg: Optional[float]
    method: str = "model"  # model|failed


class SentimentClassifier:
    """
    Singleton-friendly wrapper around a HuggingFace pipeline.
    Call `.load()` once before use; safe to call repeatedly (idempotent).
    """

    _instance: Optional["SentimentClassifier"] = None

    def __init__(self) -> None:
        self._pipe = None

    @classmethod
    def get(cls) -> "SentimentClassifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        if self._pipe is not None:
            return
        import torch
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            pipeline,
        )

        device = 0 if torch.cuda.is_available() else -1
        tokenizer = AutoTokenizer.from_pretrained(
            SENTIMENT_MODEL, cache_dir=MODEL_CACHE_DIR
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            SENTIMENT_MODEL, cache_dir=MODEL_CACHE_DIR
        )
        self._pipe = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device=device,
            top_k=None,  # return all 3 class scores
            truncation=True,
            max_length=128,
            batch_size=CLASSIFIER_BATCH_SIZE,
        )
        logger.info("sentiment_model_loaded", extra={"model": SENTIMENT_MODEL})

    # ── Public API ──────────────────────────────────────────────────────────

    def classify(self, text: str) -> SentimentResult:
        results = self.classify_batch([text])
        return results[0]

    def classify_batch(self, texts: list[str]) -> list[SentimentResult]:
        if not texts:
            return []
        if self._pipe is None:
            self.load()

        cleaned = [self._preprocess(t) for t in texts]
        try:
            raw_outputs = self._pipe(cleaned)
        except Exception as exc:
            logger.error(
                "sentiment_batch_failed", extra={"error": str(exc), "count": len(texts)}
            )
            return [
                SentimentResult(
                    label=None,
                    score=None,
                    raw_pos=None,
                    raw_neu=None,
                    raw_neg=None,
                    method="failed",
                )
                for _ in texts
            ]

        results = []
        for scores in raw_outputs:
            score_map: dict[str, float] = {}
            for item in scores:
                mapped = LABEL_MAP.get(item["label"], item["label"])
                score_map[mapped] = item["score"]

            pos = score_map.get("positive", 0.0)
            neu = score_map.get("neutral", 0.0)
            neg = score_map.get("negative", 0.0)

            best_label = max(score_map, key=lambda k: score_map[k])
            best_score = score_map[best_label]

            results.append(
                SentimentResult(
                    label=best_label,
                    score=round(best_score, 4),
                    raw_pos=round(pos, 4),
                    raw_neu=round(neu, 4),
                    raw_neg=round(neg, 4),
                    method="model",
                )
            )

        return results

    # ── Internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _preprocess(text: str) -> str:
        """Light normalisation — model handles most noise natively."""
        import re

        # Replace URLs to reduce noise
        text = re.sub(r"https?://\S+", "[URL]", text)
        # Replace @mentions (model was trained with @user → "@user" convention)
        text = re.sub(r"@\w+", "@user", text)
        # Collapse excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:512]  # hard cap before tokeniser
