from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .models import ChunkRecord, RetrievalHit
from .utils import excerpt, mixed_tokenize, normalize_whitespace


@dataclass(slots=True)
class SearchDebug:
    query: str
    vector_hits: list[dict[str, float]]
    keyword_hits: list[dict[str, float]]
    reranked_hits: list[dict[str, float]]


class SimpleBM25:
    def __init__(self, tokenized_docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.tokenized_docs = tokenized_docs
        self.k1 = k1
        self.b = b
        self.doc_lengths = [len(doc) for doc in tokenized_docs]
        self.avgdl = sum(self.doc_lengths) / max(len(self.doc_lengths), 1)
        self.term_freqs = [Counter(doc) for doc in tokenized_docs]
        self.doc_freqs: dict[str, int] = defaultdict(int)
        for freq in self.term_freqs:
            for term in freq.keys():
                self.doc_freqs[term] += 1
        self.doc_count = len(tokenized_docs)
        self.idf: dict[str, float] = {}
        for term, count in self.doc_freqs.items():
            self.idf[term] = log((self.doc_count - count + 0.5) / (count + 0.5) + 1.0)

    def score(self, query_tokens: list[str]) -> np.ndarray:
        scores = np.zeros(self.doc_count, dtype=float)
        for idx, freq in enumerate(self.term_freqs):
            doc_len = self.doc_lengths[idx] or 1
            for token in query_tokens:
                tf = freq.get(token, 0)
                if tf == 0:
                    continue
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / max(self.avgdl, 1))
                scores[idx] += self.idf.get(token, 0.0) * numerator / denominator
        return scores


class StructuralChunker:
    def __init__(self, target_chars: int = 700, overlap_chars: int = 80) -> None:
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def chunk_blocks(self, document_id: str, title: str, blocks: Iterable) -> list[ChunkRecord]:
        chunk_records: list[ChunkRecord] = []
        chunk_index = 0
        for block in blocks:
            normalized = normalize_whitespace(block.content)
            if not normalized:
                continue
            parts = self._split_long_text(normalized)
            for part in parts:
                chunk_records.append(
                    ChunkRecord(
                        id=f"{document_id}-{chunk_index:04d}",
                        document_id=document_id,
                        index=chunk_index,
                        content=part,
                        title=block.title or title,
                        page=block.page,
                        section_path=block.section_path or [title],
                        metadata=block.metadata.copy(),
                        token_count=len(mixed_tokenize(part)),
                        checksum=str(abs(hash((document_id, chunk_index, part)))),
                    )
                )
                chunk_index += 1
        return chunk_records

    def _split_long_text(self, text: str) -> list[str]:
        if len(text) <= self.target_chars:
            return [text]
        paragraphs = [segment.strip() for segment in text.split("\n") if segment.strip()]
        segments = paragraphs or [text]
        chunks: list[str] = []
        current = ""
        for segment in segments:
            if len(current) + len(segment) + 1 <= self.target_chars:
                current = f"{current}\n{segment}".strip()
                continue
            if current:
                chunks.append(current)
                overlap = current[-self.overlap_chars :] if len(current) > self.overlap_chars else current
                current = f"{overlap}\n{segment}".strip()
            else:
                chunks.extend(self._split_sentence_window(segment))
                current = ""
        if current:
            chunks.append(current)
        return chunks

    def _split_sentence_window(self, text: str) -> list[str]:
        if len(text) <= self.target_chars:
            return [text]
        sentences = [part.strip() for part in re_split_sentences(text) if part.strip()]
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= self.target_chars:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    chunks.append(current)
                    overlap = current[-self.overlap_chars :] if len(current) > self.overlap_chars else current
                    current = f"{overlap} {sentence}".strip()
                else:
                    chunks.append(sentence[: self.target_chars])
                    current = sentence[self.target_chars - self.overlap_chars :].strip()
        if current:
            chunks.append(current)
        return chunks


def re_split_sentences(text: str) -> list[str]:
    buffer = ""
    parts: list[str] = []
    for char in text:
        buffer += char
        if char in "。！？.!?;\n":
            parts.append(buffer)
            buffer = ""
    if buffer.strip():
        parts.append(buffer)
    return parts


class HybridIndex:
    def __init__(self) -> None:
        self.chunks: list[ChunkRecord] = []
        self.vectorizer = TfidfVectorizer(
            tokenizer=mixed_tokenize,
            token_pattern=None,
            lowercase=False,
            ngram_range=(1, 2),
        )
        self.matrix = None
        self.bm25: SimpleBM25 | None = None
        self.ready = False

    def rebuild(self, chunks: list[ChunkRecord]) -> None:
        self.chunks = chunks
        if not chunks:
            self.matrix = None
            self.bm25 = None
            self.ready = False
            return
        corpus = [chunk.content for chunk in chunks]
        self.matrix = self.vectorizer.fit_transform(corpus)
        self.bm25 = SimpleBM25([mixed_tokenize(text) for text in corpus])
        self.ready = True

    def search(
        self,
        query: str,
        *,
        top_k: int,
        candidate_count: int,
        doc_scope: set[str] | None = None,
        boost_doc_ids: set[str] | None = None,
    ) -> tuple[list[RetrievalHit], SearchDebug]:
        if not self.ready or self.matrix is None or self.bm25 is None:
            return [], SearchDebug(query=query, vector_hits=[], keyword_hits=[], reranked_hits=[])
        normalized_query = normalize_whitespace(query)
        query_vector = self.vectorizer.transform([normalized_query])
        vector_scores = cosine_similarity(query_vector, self.matrix).flatten()
        keyword_scores = self.bm25.score(mixed_tokenize(normalized_query))
        if doc_scope:
            mask = np.array([1.0 if chunk.document_id in doc_scope else 0.0 for chunk in self.chunks])
            vector_scores = vector_scores * mask
            keyword_scores = keyword_scores * mask
        if boost_doc_ids:
            boost = np.array([0.8 if chunk.document_id in boost_doc_ids else 0.0 for chunk in self.chunks])
            vector_scores = vector_scores + boost
            keyword_scores = keyword_scores + boost
        vector_order = np.argsort(vector_scores)[::-1][:candidate_count]
        keyword_order = np.argsort(keyword_scores)[::-1][:candidate_count]

        vector_debug = [
            {"chunk_id": self.chunks[idx].id, "score": float(vector_scores[idx])}
            for idx in vector_order
            if vector_scores[idx] > 0
        ]
        keyword_debug = [
            {"chunk_id": self.chunks[idx].id, "score": float(keyword_scores[idx])}
            for idx in keyword_order
            if keyword_scores[idx] > 0
        ]

        candidates = sorted(
            idx
            for idx in set(vector_order.tolist() + keyword_order.tolist())
            if vector_scores[idx] > 0 or keyword_scores[idx] > 0
        )
        if not candidates:
            return [], SearchDebug(query=query, vector_hits=vector_debug, keyword_hits=keyword_debug, reranked_hits=[])

        max_vector = max(vector_scores[candidates]) or 1.0
        max_keyword = max(keyword_scores[candidates]) or 1.0
        hits: list[RetrievalHit] = []
        reranked_debug: list[dict[str, float]] = []
        for idx in candidates:
            combined = 0.65 * float(vector_scores[idx] / max_vector) + 0.35 * float(keyword_scores[idx] / max_keyword)
            chunk = self.chunks[idx]
            hit = RetrievalHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                score=combined,
                vector_score=float(vector_scores[idx]),
                keyword_score=float(keyword_scores[idx]),
                title=chunk.title,
                content=excerpt(chunk.content, 420),
                page=chunk.page,
                section_path=chunk.section_path,
                metadata=chunk.metadata.copy(),
            )
            hits.append(hit)
            reranked_debug.append({"chunk_id": hit.chunk_id, "score": combined})

        hits.sort(key=lambda item: item.score, reverse=True)
        reranked_debug.sort(key=lambda item: item["score"], reverse=True)
        return hits[:top_k], SearchDebug(
            query=query,
            vector_hits=vector_debug,
            keyword_hits=keyword_debug,
            reranked_hits=reranked_debug[:top_k],
        )
