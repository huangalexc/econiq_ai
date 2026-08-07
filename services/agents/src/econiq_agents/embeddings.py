"""Embeddings for candidate retrieval (tech rec §7).

Used to *narrow* what the resolution agent is shown, never to decide anything.
Retrieval is deterministic and cheap; clustering judgement is the agent's and
expensive. Getting that split right is most of what keeps the LLM bill sane at
volume.

``HashingEmbedder`` is a real, deterministic embedder — but a lexical one, not a
semantic one. It exists so the pipeline, the tests and offline development all
work without a vendor. A semantic provider plugs in behind ``Embedder`` the same
way a model provider plugs in behind ``LLMProvider``.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from econiq_data_models import EMBEDDING_DIM, Embedding, EmbeddingKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_TOKEN = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Hashed token n-grams, L2-normalized.

    Deterministic and dependency-free, so a test can assert on similarity
    without a network call. It captures lexical overlap only: two reports of the
    same event that share no vocabulary will not look similar. That is a real
    limitation of retrieval quality, not of correctness — the agent still sees
    every candidate inside the time window.
    """

    model = "hashing-v1"

    def __init__(self, dimensions: int = EMBEDDING_DIM, ngram: int = 2) -> None:
        self.dimensions = dimensions
        self.ngram = ngram

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN.findall(text.lower())
        features = list(tokens)
        for size in range(2, self.ngram + 1):
            features.extend(" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1))
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            # The sign bit spreads collisions instead of letting them pile up.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity, safe on zero vectors."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


class EmbeddingStore:
    """Persists vectors alongside the nodes they describe.

    ``source_hash`` records what was embedded, so a stale vector — text changed,
    or the embedding model changed — is detectable rather than silently wrong.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], embedder: Embedder
    ) -> None:
        self.session_factory = session_factory
        self.embedder = embedder

    async def upsert(self, node_id: uuid.UUID, kind: EmbeddingKind, text: str) -> list[float]:
        vector = self.embedder.embed([text])[0]
        source_hash = hashlib.sha256(text.encode()).hexdigest()
        async with self.session_factory() as session:
            existing = await self._find(session, node_id, kind)
            if existing is not None:
                if existing.source_hash == source_hash:
                    return list(existing.embedding)
                # Re-embedding is an update of a derived artifact, not of
                # evidence, so overwriting here does not violate the
                # nothing-is-destroyed rule.
                existing.embedding = vector
                existing.source_hash = source_hash
            else:
                session.add(
                    Embedding(
                        node_id=node_id,
                        kind=kind,
                        model=self.embedder.model,
                        dimensions=len(vector),
                        embedding=vector,
                        source_hash=source_hash,
                    )
                )
            await session.commit()
        return vector

    async def _find(
        self, session: AsyncSession, node_id: uuid.UUID, kind: EmbeddingKind
    ) -> Embedding | None:
        result = await session.execute(
            select(Embedding).where(
                Embedding.node_id == node_id,
                Embedding.kind == kind,
                Embedding.model == self.embedder.model,
            )
        )
        return result.scalar_one_or_none()

    async def nearest(
        self,
        vector: Sequence[float],
        kind: EmbeddingKind,
        *,
        limit: int = 20,
        max_distance: float = 0.5,
        exclude: Sequence[uuid.UUID] = (),
    ) -> list[tuple[uuid.UUID, float]]:
        """Nearest neighbours by cosine distance, closest first.

        Runs in Postgres via pgvector rather than in Python: at Phase 2 volumes
        the candidate set is the whole historical corpus.
        """
        distance = Embedding.embedding.cosine_distance(list(vector))
        query = (
            select(Embedding.node_id, distance.label("distance"))
            .where(Embedding.kind == kind, Embedding.model == self.embedder.model)
            .order_by(distance)
            .limit(limit)
        )
        if exclude:
            query = query.where(Embedding.node_id.notin_(list(exclude)))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).all()
        return [(row.node_id, float(row.distance)) for row in rows if row.distance <= max_distance]
