from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import HTTPError

from .config import get_settings
from .schemas import ChatRequest, ChatResponse, HealthResponse, Source
from .services.ollama_client import OllamaClient
from .services.paperless_client import PaperlessClient
from .services.retrieval import (
    build_grounded_backup_answer,
    FALLBACK_SENTENCE,
    rank_documents_for_question,
    SYSTEM_PROMPT,
    build_user_prompt,
    estimate_confidence,
    sanitize_answer,
)

settings = get_settings()
paperless_client = PaperlessClient(
    base_url=settings.paperless_base_url,
    token=settings.paperless_token,
    timeout=settings.request_timeout_seconds,
)
ollama_client = OllamaClient(
    base_url=settings.ollama_base_url,
    model=settings.ollama_model,
    timeout=settings.request_timeout_seconds,
)

app = FastAPI(title="Meine_chatbot API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", detail="API is running")


@app.get("/api/health/paperless", response_model=HealthResponse)
async def health_paperless() -> HealthResponse:
    ok, detail = await paperless_client.health_check()
    if not ok:
        raise HTTPException(status_code=503, detail=f"Paperless unavailable: {detail}")
    return HealthResponse(status="ok", detail=detail)


@app.get("/api/health/ollama", response_model=HealthResponse)
async def health_ollama() -> HealthResponse:
    ok, detail = await ollama_client.health_check()
    if not ok:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {detail}")
    return HealthResponse(status="ok", detail=detail, model=settings.ollama_model)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    requested_ids = re.findall(r"\bID\s*:\s*(\d+)\b", question, flags=re.IGNORECASE)

    id_documents = []
    if requested_ids:
        try:
            id_documents = await paperless_client.get_documents_by_ids(requested_ids)
        except HTTPError as exc:
            error_message = str(exc) or exc.__class__.__name__
            raise HTTPException(status_code=502, detail=f"Paperless ID fetch failed: {error_message}") from exc

    explicit_list_scope = bool(requested_ids) and bool(
        re.search(r"\b(ces documents|cette liste|ci[- ]?dessus|documents suivants)\b", question, flags=re.IGNORECASE)
    )

    search_documents = []
    search_error: HTTPError | None = None
    if not explicit_list_scope:
        try:
            dynamic_top_k = max(settings.top_k, len(requested_ids) + 2)
            search_documents = await paperless_client.search_documents(question, top_k=dynamic_top_k)
        except HTTPError as exc:
            search_error = exc

    if search_error and not id_documents:
        error_message = str(search_error) or search_error.__class__.__name__
        raise HTTPException(status_code=502, detail=f"Paperless query failed: {error_message}") from search_error

    merged_documents = []
    seen_ids: set[str] = set()
    for document in [*id_documents, *search_documents]:
        if document.id in seen_ids:
            continue
        seen_ids.add(document.id)
        merged_documents.append(document)

    documents = merged_documents

    documents = rank_documents_for_question(question, documents)

    user_prompt = build_user_prompt(
        question=question,
        documents=documents,
        max_chars=settings.max_context_chars,
    )

    answer = ""
    used_backup_answer = False
    try:
        answer = await ollama_client.chat(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    except HTTPError:
        answer = ""

    answer = sanitize_answer(answer)

    if documents and (not answer or answer == FALLBACK_SENTENCE):
        answer = build_grounded_backup_answer(question, documents)
        used_backup_answer = True

    if not documents or not answer:
        answer = FALLBACK_SENTENCE

    confidence = estimate_confidence(answer, documents)
    if used_backup_answer and confidence == "high":
        confidence = "medium"

    sources = [
        Source(title=document.title, id=document.id, snippet=document.snippet)
        for document in documents
    ]

    return ChatResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
    )
