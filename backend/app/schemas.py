from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str
    id: str
    snippet: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    confidence: str


class HealthResponse(BaseModel):
    status: str
    detail: str
    model: str | None = None
