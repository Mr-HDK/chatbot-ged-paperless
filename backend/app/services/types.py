from dataclasses import dataclass


@dataclass(slots=True)
class RetrievedDocument:
    id: str
    title: str
    snippet: str
    score: float | None = None

