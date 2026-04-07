"""
Brand Relevance Classifier
──────────────────────────
Decision pipeline:
  1. Hard exclusion check  → score = 0.0, IRRELEVANT
  2. Primary keyword match → score = 1.0, RELEVANT
  3. Secondary + context   → score = 0.7, RELEVANT
  4. Secondary only        → score = 0.35, BORDERLINE
                             (flagged irrelevant unless embedding confirms)
  5. Embedding similarity  → optional gate on borderline cases

Scoring is deterministic and fast by default.
Embedding fallback is opt-in (RELEVANCE_EMBEDDING_ENABLED=true).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config.settings import (
    MODEL_CACHE_DIR,
    RELEVANCE_EMBEDDING_ENABLED,
    RELEVANCE_EMBEDDING_MODEL,
    RELEVANCE_EMBEDDING_THRESHOLD,
)

KEYWORDS_PATH = Path(__file__).parent.parent / "config" / "keywords.yaml"


@dataclass
class RelevanceResult:
    is_relevant: bool
    score: float  # 0.0 – 1.0
    method: str  # keyword|embedding|hybrid
    matched_primary: list[str] = field(default_factory=list)
    matched_secondary: list[str] = field(default_factory=list)
    matched_context: list[str] = field(default_factory=list)
    matched_exclusions: list[str] = field(default_factory=list)
    derived_labels: list[str] = field(default_factory=list)


class BrandRelevanceClassifier:
    """
    Stateless relevance classifier. Thread-safe after __init__.
    Loading embeddings is lazy and guarded by a flag.
    """

    def __init__(self, brand_id: str = "yeet_casino") -> None:
        cfg = yaml.safe_load(KEYWORDS_PATH.read_text())
        brand = next(b for b in cfg["brand_queries"] if b["id"] == brand_id)

        self._primary = [k.lower() for k in brand["primary_keywords"]]
        self._secondary = [k.lower() for k in brand["secondary_keywords"]]
        self._exclusions = [k.lower() for k in brand["exclusion_keywords"]]
        self._soft_excl = [k.lower() for k in brand.get("soft_exclusion_keywords", [])]
        self._context = [k.lower() for k in brand["context_required_for_secondary"]]
        self._derived_rules: dict[str, list[str]] = {
            label: [k.lower() for k in meta["keywords"]]
            for label, meta in cfg["derived_labels"].items()
        }

        # Optional embedding gate
        self._embedder = None
        self._brand_embedding = None
        if RELEVANCE_EMBEDDING_ENABLED:
            self._load_embedder(brand["display_name"])

    def _load_embedder(self, brand_display: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._embedder = SentenceTransformer(
            RELEVANCE_EMBEDDING_MODEL, cache_folder=MODEL_CACHE_DIR
        )
        self._brand_embedding = self._embedder.encode(
            [brand_display], normalize_embeddings=True
        )

    # ── Public API ──────────────────────────────────────────────────────────

    @staticmethod
    def _norm(s: str) -> str:
        """Normalise text: strip underscores so user typos like 'y_eet' still match."""
        return s.replace("_", "")

    def classify(self, text: str) -> RelevanceResult:
        t = text.lower()
        tn = self._norm(t)

        # 1. Hard exclusion
        excl_hits = [k for k in self._exclusions if self._norm(k) in tn]
        if excl_hits:
            return RelevanceResult(
                is_relevant=False,
                score=0.0,
                method="keyword",
                matched_exclusions=excl_hits,
            )

        prim_hits = [k for k in self._primary if self._norm(k) in tn]
        sec_hits = [k for k in self._secondary if self._norm(k) in tn]
        ctx_hits = [k for k in self._context if k in t]
        soft_hits = [k for k in self._soft_excl if self._norm(k) in tn]
        derived = self._classify_derived(t)

        # 2. Primary match → always relevant
        if prim_hits:
            score = min(1.0, 0.85 + 0.05 * len(prim_hits))
            score -= 0.1 * len(soft_hits)  # soft penalty
            score = max(0.6, score)
            return RelevanceResult(
                is_relevant=True,
                score=round(score, 3),
                method="keyword",
                matched_primary=prim_hits,
                matched_secondary=sec_hits,
                matched_context=ctx_hits,
                derived_labels=derived,
            )

        # 3. Secondary + context → relevant
        if sec_hits and ctx_hits:
            score = 0.55 + 0.05 * len(sec_hits) + 0.05 * len(ctx_hits)
            score -= 0.1 * len(soft_hits)
            score = max(0.4, min(0.85, score))
            return RelevanceResult(
                is_relevant=True,
                score=round(score, 3),
                method="keyword",
                matched_secondary=sec_hits,
                matched_context=ctx_hits,
                derived_labels=derived,
            )

        # 4. Secondary only → borderline, try embedding
        if sec_hits:
            base_score = 0.25 + 0.03 * len(sec_hits)
            if self._embedder is not None:
                emb_score = self._embedding_similarity(text)
                if emb_score >= RELEVANCE_EMBEDDING_THRESHOLD:
                    return RelevanceResult(
                        is_relevant=True,
                        score=round((base_score + emb_score) / 2, 3),
                        method="hybrid",
                        matched_secondary=sec_hits,
                        derived_labels=derived,
                    )
            return RelevanceResult(
                is_relevant=False,
                score=round(base_score, 3),
                method="keyword",
                matched_secondary=sec_hits,
            )

        # 5. No match
        return RelevanceResult(is_relevant=False, score=0.0, method="keyword")

    def classify_batch(self, texts: list[str]) -> list[RelevanceResult]:
        return [self.classify(t) for t in texts]

    # ── Internals ───────────────────────────────────────────────────────────

    def _classify_derived(self, text_lower: str) -> list[str]:
        tn = self._norm(text_lower)
        return [
            label
            for label, keywords in self._derived_rules.items()
            if any(self._norm(k) in tn for k in keywords)
        ]

    def _embedding_similarity(self, text: str) -> float:
        import numpy as np

        if self._embedder is None or self._brand_embedding is None:
            return 0.0
        emb = self._embedder.encode([text], normalize_embeddings=True)
        sim = float(np.dot(emb, self._brand_embedding.T).squeeze())
        return max(0.0, min(1.0, sim))
