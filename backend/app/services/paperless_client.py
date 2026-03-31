from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx

from .types import RetrievedDocument


class PaperlessClient:
    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Token {token}"}
        self._timeout = timeout

    async def search_documents(self, query: str, top_k: int) -> list[RetrievedDocument]:
        attempts = self._build_query_attempts(query)
        page_size = max(10, top_k * 3)
        query_keywords = self._extract_keywords(self._normalize_for_search(query))
        unique_documents: dict[str, tuple[RetrievedDocument, int]] = {}
        max_pool_size = max(top_k * 8, 24)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in attempts:
                response = await client.get(
                    f"{self._base_url}/api/documents/",
                    headers=self._headers,
                    params={"query": attempt, "page_size": page_size},
                )
                response.raise_for_status()

                payload = response.json()
                raw_documents = self._extract_list(payload)
                for item in raw_documents:
                    document = self._to_document(item)
                    if not document:
                        continue
                    score = self._query_match_score(document, query_keywords)
                    existing = unique_documents.get(document.id)
                    if not existing or score > existing[1]:
                        unique_documents[document.id] = (document, score)
                    if len(unique_documents) >= max_pool_size:
                        break
                if len(unique_documents) >= max_pool_size:
                    break

            if len(unique_documents) < top_k and self._is_listing_request(query):
                remaining = top_k - len(unique_documents)
                fallback = await self._list_recent_documents(client, max(remaining, 3))
                for document in fallback:
                    score = self._query_match_score(document, query_keywords)
                    unique_documents.setdefault(document.id, (document, score))
                    if len(unique_documents) >= max_pool_size:
                        break

        ranked_documents = sorted(
            unique_documents.values(),
            key=lambda item: item[1],
            reverse=True,
        )
        selected = [item[0] for item in ranked_documents[:top_k]]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._hydrate_documents_with_content(client, selected, query_keywords)

    async def get_documents_by_ids(self, document_ids: list[str]) -> list[RetrievedDocument]:
        unique_ids: list[str] = []
        seen: set[str] = set()
        for raw in document_ids:
            clean = str(raw).strip()
            if clean and clean not in seen:
                seen.add(clean)
                unique_ids.append(clean)

        documents: list[RetrievedDocument] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for document_id in unique_ids:
                response = await client.get(
                    f"{self._base_url}/api/documents/{document_id}/",
                    headers=self._headers,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    document = self._to_document(payload)
                    if document:
                        documents.append(document)
        return documents

    async def health_check(self) -> tuple[bool, str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.get(
                    f"{self._base_url}/api/documents/",
                    headers=self._headers,
                    params={"page_size": 1},
                )
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)
        return True, "Paperless reachable"

    @staticmethod
    def _extract_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            candidates = payload.get("results")
            if isinstance(candidates, list):
                return [item for item in candidates if isinstance(item, dict)]
        return []

    def _to_document(self, item: dict[str, Any]) -> RetrievedDocument | None:
        raw_id = item.get("id") or item.get("document_id") or item.get("pk")
        if raw_id is None:
            return None

        title = str(item.get("title") or item.get("name") or f"Document {raw_id}").strip()
        snippet = self._pick_snippet(item)
        if not snippet:
            snippet = "Aucun extrait disponible."

        raw_score = item.get("score") or item.get("_score")
        score: float | None = None
        if raw_score is not None:
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = None

        return RetrievedDocument(
            id=str(raw_id),
            title=title[:300],
            snippet=snippet,
            score=score,
        )

    @staticmethod
    def _pick_snippet(item: dict[str, Any]) -> str:
        candidates = [
            item.get("snippet"),
            item.get("content"),
            item.get("text"),
            item.get("summary"),
            item.get("highlight"),
        ]

        highlights = item.get("highlights")
        if isinstance(highlights, list):
            for value in highlights:
                if isinstance(value, str):
                    candidates.append(value)
                elif isinstance(value, dict):
                    for sub in value.values():
                        if isinstance(sub, str):
                            candidates.append(sub)

        for candidate in candidates:
            normalized = PaperlessClient._normalize_text(candidate)
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _normalize_text(value: Any, max_chars: int | None = 1400) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        without_tags = re.sub(r"<[^>]+>", " ", value)
        clean = " ".join(without_tags.split())
        if max_chars is not None:
            clean = clean[:max_chars]
        return clean.strip()

    async def _list_recent_documents(
        self,
        client: httpx.AsyncClient,
        limit: int,
    ) -> list[RetrievedDocument]:
        response = await client.get(
            f"{self._base_url}/api/documents/",
            headers=self._headers,
            params={"page_size": limit},
        )
        response.raise_for_status()
        payload = response.json()
        raw_documents = self._extract_list(payload)
        documents: list[RetrievedDocument] = []
        for item in raw_documents:
            document = self._to_document(item)
            if document:
                documents.append(document)
        return documents

    async def _hydrate_documents_with_content(
        self,
        client: httpx.AsyncClient,
        documents: list[RetrievedDocument],
        query_keywords: list[str],
    ) -> list[RetrievedDocument]:
        hydrated: list[RetrievedDocument] = []
        for document in documents:
            enriched = document
            try:
                response = await client.get(
                    f"{self._base_url}/api/documents/{document.id}/",
                    headers=self._headers,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    content = self._normalize_text(payload.get("content"), max_chars=None)
                    if content:
                        excerpt = self._extract_relevant_excerpt(content, query_keywords, max_chars=8000)
                        enriched = RetrievedDocument(
                            id=document.id,
                            title=document.title,
                            snippet=excerpt,
                            score=document.score,
                        )
            except Exception:
                enriched = document
            hydrated.append(enriched)
        return hydrated

    @staticmethod
    def _extract_relevant_excerpt(content: str, keywords: list[str], max_chars: int) -> str:
        if len(content) <= max_chars:
            return content

        usable_keywords = [word for word in keywords if len(word) >= 4]
        if not usable_keywords:
            return content[:max_chars]

        lower = content.lower()
        windows: list[tuple[int, int]] = []
        for keyword in usable_keywords[:8]:
            start = 0
            while True:
                index = lower.find(keyword.lower(), start)
                if index < 0:
                    break
                left = max(0, index - 450)
                right = min(len(content), index + 950)
                windows.append((left, right))
                start = index + len(keyword)
                if len(windows) >= 8:
                    break
            if len(windows) >= 8:
                break

        if not windows:
            return content[:max_chars]

        windows.sort(key=lambda item: item[0])
        merged: list[tuple[int, int]] = []
        for left, right in windows:
            if not merged or left > merged[-1][1] + 30:
                merged.append((left, right))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))

        chunks: list[str] = []
        current_len = 0
        for left, right in merged:
            piece = content[left:right].strip()
            if not piece:
                continue
            separator = "\n...\n" if chunks else ""
            candidate_len = current_len + len(separator) + len(piece)
            if candidate_len > max_chars:
                remaining = max_chars - current_len - len(separator)
                if remaining > 120:
                    chunks.append(separator + piece[:remaining])
                break
            chunks.append(separator + piece)
            current_len = candidate_len

        extracted = "".join(chunks).strip()
        return extracted if extracted else content[:max_chars]

    @staticmethod
    def _build_query_attempts(query: str) -> list[str]:
        attempts: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            key = value.strip()
            if not key or key in seen:
                return
            seen.add(key)
            attempts.append(key)

        add(query)
        normalized = PaperlessClient._normalize_for_search(query)
        add(normalized)

        keywords = PaperlessClient._extract_keywords(normalized)
        if keywords:
            add(" ".join(keywords[:6]))
            expanded_keywords = list(keywords)
            if "nime" in expanded_keywords and "nimes" not in expanded_keywords:
                expanded_keywords.append("nimes")
            if "nimes" in expanded_keywords and "france" not in expanded_keywords:
                expanded_keywords.append("france")
            for word in list(expanded_keywords):
                if word.endswith("s") and len(word) >= 5:
                    singular = word[:-1]
                    if singular not in expanded_keywords:
                        expanded_keywords.append(singular)

            for word in expanded_keywords[:8]:
                add(word)
            if len(expanded_keywords) >= 2:
                add(f"{expanded_keywords[0]} {expanded_keywords[1]}")
            if len(expanded_keywords) >= 3:
                add(f"{expanded_keywords[0]} {expanded_keywords[1]} {expanded_keywords[2]}")

        keyword_set = set(keywords)
        if {"conge", "conges"} & keyword_set:
            add("reglement personnel conge")
            add("reglement du personnel")
            add("politique rh conges")
        if {"engagement", "temporaire"} & keyword_set:
            add("reglement personnel engagement temporaire")
            add("engagement a titre temporaire")
            add("politique rh oss")

        return attempts

    @staticmethod
    def _extract_keywords(normalized_query: str) -> list[str]:
        stopwords = {
            "combien",
            "quel",
            "quelle",
            "quels",
            "quelles",
            "jour",
            "jours",
            "droit",
            "droits",
            "avons",
            "avez",
            "oss",
            "le",
            "la",
            "les",
            "de",
            "des",
            "du",
            "un",
            "une",
            "et",
            "en",
            "a",
            "au",
            "aux",
            "dans",
            "sur",
            "pour",
            "avec",
            "est",
            "y",
            "que",
            "qui",
            "donne",
            "moi",
            "tout",
            "tous",
            "cherche",
            "chercher",
            "dossier",
            "dossiers",
            "fichiers",
            "stp",
            "svp",
            "the",
            "and",
            "in",
            "to",
            "of",
        }
        words = [word for word in normalized_query.split() if len(word) >= 3 and word not in stopwords]
        return words

    @staticmethod
    def _is_listing_request(query: str) -> bool:
        normalized = query.lower()
        intents = [
            "au hasard",
            "random",
            "liste",
            "list",
            "titres",
            "titre",
            "documents",
            "fichiers",
            "montre",
            "affiche",
        ]
        return any(intent in normalized for intent in intents)

    @staticmethod
    def _query_match_score(document: RetrievedDocument, keywords: list[str]) -> int:
        if not keywords:
            return 0
        haystack = PaperlessClient._normalize_for_search(f"{document.title} {document.snippet}")
        tokens = set(haystack.split())
        score = 0
        strong_terms = {
            "nimes",
            "france",
            "adaptwap",
            "facture",
            "mission",
            "reglement",
            "personnel",
            "conge",
            "conges",
            "engagement",
            "temporaire",
        }
        for keyword in keywords:
            if keyword in tokens:
                score += 3 if keyword in strong_terms else 1
        return score

    @staticmethod
    def _normalize_for_search(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        no_accents = "".join(char for char in normalized if not unicodedata.combining(char))
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", no_accents.lower().replace("'", " "))
        return " ".join(clean.split())
