from __future__ import annotations

import re
import unicodedata

from .types import RetrievedDocument

SYSTEM_PROMPT = """You are Meine_chatbot, an internal document assistant.

You must ONLY answer using the provided document context.

If the answer is not present in the context, say clearly:
'I don't have enough information in the documents to answer this.'

Do NOT invent information.
Do NOT guess.
Do NOT add external knowledge.

Answer in clear, professional French.

Always cite the documents used when possible."""

FALLBACK_SENTENCE = "I don't have enough information in the documents to answer this."
UNCERTAINTY_MARKERS = (
    "i don't have enough information",
    "je n ai pas assez d information",
    "je n'ai pas assez d information",
    "je n ai pas assez d'informations",
    "je n'ai pas assez d'informations",
    "pas assez d information",
    "pas assez d informations",
    "insufficient information",
)


def build_user_prompt(question: str, documents: list[RetrievedDocument], max_chars: int) -> str:
    context_blocks: list[str] = []
    current_size = 0

    for index, doc in enumerate(documents, start=1):
        block = (
            f"[SOURCE {index}]\n"
            f"ID: {doc.id}\n"
            f"TITRE: {doc.title}\n"
            f"EXTRAIT: {doc.snippet}\n"
        )
        if current_size + len(block) > max_chars:
            break
        context_blocks.append(block)
        current_size += len(block)

    context_text = "\n".join(context_blocks).strip()
    if not context_text:
        context_text = "Aucun document pertinent trouve."

    return (
        "Contexte documentaire:\n"
        f"{context_text}\n\n"
        "Question utilisateur:\n"
        f"{question}\n\n"
        "Instruction finale: reponds strictement avec les informations presentes dans le contexte."
    )


def estimate_confidence(answer: str, used_sources: list[RetrievedDocument]) -> str:
    answer_lower = answer.lower()
    if _is_uncertain_answer(answer_lower):
        return "low"
    if not used_sources:
        return "low"
    if len(used_sources) >= 4:
        return "high"
    return "medium"


def sanitize_answer(answer: str) -> str:
    text = (answer or "").strip()
    if not text:
        return FALLBACK_SENTENCE

    lowered = text.lower()
    reasoning_markers = (
        "okay, let's",
        "let's tackle",
        "i need to",
        "first, i need",
        "the user is asking",
    )
    if lowered.startswith(reasoning_markers):
        return FALLBACK_SENTENCE

    final_markers = ("reponse finale:", "réponse finale:", "final answer:")
    for marker in final_markers:
        position = lowered.find(marker)
        if position >= 0:
            candidate = text[position + len(marker) :].strip()
            if candidate:
                return candidate

    return text


def _is_uncertain_answer(answer_lower: str) -> bool:
    return any(marker in answer_lower for marker in UNCERTAINTY_MARKERS)


def build_grounded_backup_answer(question: str, documents: list[RetrievedDocument]) -> str:
    if not documents:
        return FALLBACK_SENTENCE

    normalized_question = _normalize(question)
    list_intent = _is_list_intent(normalized_question)
    summary_intent = _is_summary_intent(normalized_question)
    count_facture_intent = "combien" in normalized_question and (
        "facture" in normalized_question or "factures" in normalized_question
    )
    facture_date_intent = (
        ("facture" in normalized_question or "factures" in normalized_question)
        and any(term in normalized_question for term in ["date", "dates", "dated", "emission"])
    )
    facture_ttc_intent = (
        ("facture" in normalized_question or "factures" in normalized_question)
        and any(term in normalized_question for term in ["ttc", "prix", "montant"])
    )

    ranked = rank_documents_for_question(question, documents)

    if facture_ttc_intent and facture_date_intent:
        facture_docs = [
            doc
            for doc in ranked
            if _has_any_token(_normalize(f"{doc.title} {doc.snippet}"), {"facture", "factures"})
        ]
        if not facture_docs:
            return FALLBACK_SENTENCE

        lines: list[str] = []
        total_ttc = 0.0
        has_numeric_ttc = False
        for item in facture_docs[:6]:
            ttc = _extract_ttc_amount(item.snippet)
            doc_date = _extract_document_date(item.snippet)
            date_text = doc_date if doc_date else "date non trouvee"
            if ttc:
                lines.append(f"- {item.title} (ID: {item.id}): date = {date_text}, TTC = {ttc}")
                try:
                    total_ttc += float(ttc)
                    has_numeric_ttc = True
                except ValueError:
                    pass
            else:
                lines.append(f"- {item.title} (ID: {item.id}): date = {date_text}, TTC non trouve")
        summary = "Voici les dates et TTC trouves dans les factures:\n" + "\n".join(lines)
        if has_numeric_ttc:
            summary += f"\n\nTotal TTC cumule (documents affiches): {total_ttc:.3f}"
        return summary

    if facture_ttc_intent:
        facture_docs = [
            doc
            for doc in ranked
            if _has_any_token(_normalize(f"{doc.title} {doc.snippet}"), {"facture", "factures"})
        ]
        if not facture_docs:
            return FALLBACK_SENTENCE

        lines: list[str] = []
        total_ttc = 0.0
        has_numeric_ttc = False
        for item in facture_docs[:6]:
            ttc = _extract_ttc_amount(item.snippet)
            if ttc:
                lines.append(f"- {item.title} (ID: {item.id}): TTC = {ttc}")
                try:
                    total_ttc += float(ttc)
                    has_numeric_ttc = True
                except ValueError:
                    pass
            else:
                lines.append(f"- {item.title} (ID: {item.id}): TTC non trouve dans l'extrait")
        summary = "Oui, voici les factures trouvees et leurs TTC lorsqu'ils sont lisibles:\n" + "\n".join(lines)
        if has_numeric_ttc:
            summary += f"\n\nTotal TTC cumule (documents affiches): {total_ttc:.3f}"
        return summary

    if facture_date_intent:
        facture_docs = [
            doc
            for doc in ranked
            if _has_any_token(_normalize(f"{doc.title} {doc.snippet}"), {"facture", "factures"})
        ]
        if not facture_docs:
            return FALLBACK_SENTENCE

        lines: list[str] = []
        for item in facture_docs[:6]:
            doc_date = _extract_document_date(item.snippet)
            if doc_date:
                lines.append(f"- {item.title} (ID: {item.id}): date = {doc_date}")
            else:
                lines.append(f"- {item.title} (ID: {item.id}): date non trouvee dans l'extrait")
        return "Voici les dates trouvees dans les factures:\n" + "\n".join(lines)

    if count_facture_intent:
        facture_docs = [
            doc
            for doc in ranked
            if _has_any_token(_normalize(f"{doc.title} {doc.snippet}"), {"facture", "factures"})
        ]
        count = len(facture_docs)
        selected = facture_docs[:5] if facture_docs else ranked[:5]
        lines = [f"- {item.title} (ID: {item.id})" for item in selected]
        return f"Dans les documents retrouves, j'ai trouve {count} facture(s) pertinente(s):\n" + "\n".join(lines)

    location_terms = [term for term in ["france", "nimes", "nime"] if term in normalized_question]
    location_check_intent = (
        location_terms
        and any(term in normalized_question for term in ["document", "mission", "mentionne", "mention"])
        and not summary_intent
    )
    if location_check_intent:
        matched = [
            doc
            for doc in ranked
            if any(term in _normalize(f"{doc.title} {doc.snippet}") for term in location_terms)
        ]
        if matched:
            selected = matched[:4]
            lines = [f"- {item.title} (ID: {item.id})" for item in selected]
            return "Oui, des documents mentionnent ces termes:\n" + "\n".join(lines)

    if list_intent:
        limit = 3 if "trois" in normalized_question else 5
        selected = ranked[:limit]
        lines = [f"- {item.title} (ID: {item.id})" for item in selected]
        return "Voici des documents pertinents trouves:\n" + "\n".join(lines)

    if summary_intent:
        best = _select_best_document_for_summary(normalized_question, ranked)
        snippet = best.snippet[:420].strip()
        intro = ""
        if any(token in normalized_question for token in ["y a", "y a t", "il y a", "existe"]):
            intro = "Oui, il y a au moins un document pertinent.\n"
        return (
            f"{intro}Resume base sur le document le plus pertinent ({best.title}, ID: {best.id}):\n"
            f"{snippet}"
        )

    selected = ranked[:4]
    lines = [f"- {item.title} (ID: {item.id})" for item in selected]
    return (
        "Je ne peux pas confirmer une reponse unique avec certitude, "
        "mais ces documents semblent pertinents:\n"
        + "\n".join(lines)
    )


def _rank_documents(documents: list[RetrievedDocument], keywords: list[str]) -> list[RetrievedDocument]:
    if not keywords:
        return documents

    scored: list[tuple[int, RetrievedDocument]] = []
    for document in documents:
        haystack = _normalize(f"{document.title} {document.snippet}")
        tokens = set(haystack.split())
        score = sum(1 for keyword in keywords if keyword in tokens)
        scored.append((score, document))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored]


def rank_documents_for_question(question: str, documents: list[RetrievedDocument]) -> list[RetrievedDocument]:
    normalized_question = _normalize(question)
    keywords = _extract_question_keywords(normalized_question)
    base_ranked = _rank_documents(documents, keywords)
    if not base_ranked:
        return base_ranked

    hr_intent = any(
        token in normalized_question
        for token in [
            "conge",
            "conges",
            "reglement",
            "personnel",
            "politique",
            "engagement",
            "temporaire",
            "contrat",
            "duree",
            "droits",
        ]
    )

    scored_docs: list[tuple[int, RetrievedDocument, str]] = []
    for doc in base_ranked:
        text = _normalize(f"{doc.title} {doc.snippet}")
        title = _normalize(doc.title)
        score = 0

        if "mission" in normalized_question:
            if _has_any_token(title, {"mission", "missions"}):
                score += 8
            elif _has_any_token(text, {"mission", "missions"}):
                score += 3
        if any(token in normalized_question for token in ["nimes", "nime", "france"]):
            if "nimes" in text or "france" in text:
                score += 6
        if "facture" in normalized_question or "factures" in normalized_question:
            if _has_any_token(text, {"facture", "factures"}):
                score += 8
            if "oiseau bleu" in text:
                score += 6
        if "prerequis" in title and "mission" in normalized_question:
            score -= 4
        if "audit" in title and "mission" in normalized_question:
            score -= 3
        if hr_intent:
            if _has_any_token(title, {"reglement", "personnel", "rh"}):
                score += 10
            if _has_any_token(text, {"reglement", "personnel", "conge", "conges", "politique"}):
                score += 8
            if _has_any_token(text, {"chapitre", "article", "conditions", "recrutement"}):
                score += 2

        scored_docs.append((score, doc, text))

    if "facture" in normalized_question or "factures" in normalized_question:
        facture_only = [
            item
            for item in scored_docs
            if _has_any_token(item[2], {"facture", "factures"}) or "oiseau bleu" in item[2]
        ]
        if facture_only:
            scored_docs = facture_only
    elif hr_intent:
        hr_only = [
            item
            for item in scored_docs
            if _has_any_token(
                item[2],
                {"reglement", "personnel", "conge", "conges", "politique", "engagement", "temporaire"},
            )
        ]
        if hr_only:
            scored_docs = hr_only

    scored_docs.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored_docs]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    no_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    clean = re.sub(r"[^a-zA-Z0-9\s]", " ", no_accents.lower())
    return " ".join(clean.split())


def _extract_question_keywords(normalized_question: str) -> list[str]:
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
        "a",
        "on",
        "oss",
        "dans",
        "avec",
        "pour",
        "donne",
        "dossier",
        "dossiers",
        "fichier",
        "fichiers",
        "documents",
        "document",
        "trois",
        "titre",
        "titres",
        "cherche",
        "chercher",
        "mission",
        "question",
        "tous",
        "tout",
        "une",
        "des",
        "les",
        "aux",
        "sur",
        "from",
        "that",
        "this",
        "stp",
        "svp",
    }
    return [word for word in normalized_question.split() if len(word) >= 4 and word not in stopwords]


def _extract_ttc_amount(snippet: str) -> str:
    raw_patterns = [
        r"total\s*t\W*t\W*c\W*[:=]?\s*([0-9]+(?:[.,][0-9]{1,3})?)",
        r"\bttc\b\W*[:=]?\s*([0-9]+(?:[.,][0-9]{1,3})?)",
    ]
    for pattern in raw_patterns:
        match = re.search(pattern, snippet, flags=re.IGNORECASE)
        if match:
            return match.group(1).replace(",", ".")

    patterns = [
        r"total\s*t\s*t\s*c\s*([0-9][0-9\s]*)",
        r"\bttc\b\s*([0-9][0-9\s]*)",
    ]
    normalized = _normalize(snippet)
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            compact = " ".join(match.group(1).split())
            parts = compact.split(" ")
            if len(parts) >= 2 and len(parts[1]) == 3:
                return f"{parts[0]}.{parts[1]}"
            return parts[0]
    return ""


def _extract_document_date(snippet: str) -> str:
    raw_patterns = [
        r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
        r"\b(\d{1,2}\s+(?:janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre)\s+\d{4})\b",
    ]
    for pattern in raw_patterns:
        match = re.search(pattern, snippet, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    normalized = _normalize(snippet)
    match = re.search(r"\b(\d{1,2}\s+\d{1,2}\s+\d{4})\b", normalized)
    if match:
        parts = match.group(1).split()
        if len(parts) == 3:
            return f"{parts[0]}/{parts[1]}/{parts[2]}"
    return ""


def _is_list_intent(normalized_question: str) -> bool:
    return any(
        term in normalized_question
        for term in ["titre", "titres", "liste", "documents", "fichiers", "au hasard", "random", "donne"]
    )


def _is_summary_intent(normalized_question: str) -> bool:
    return any(
        term in normalized_question
        for term in ["resume", "resumer", "c est quoi", "c quoi", "explique", "s est passe", "resum"]
    )


def _has_any_token(normalized_text: str, expected_tokens: set[str]) -> bool:
    tokens = set(normalized_text.split())
    return any(token in tokens for token in expected_tokens)


def _select_best_document_for_summary(
    normalized_question: str,
    ranked: list[RetrievedDocument],
) -> RetrievedDocument:
    if not ranked:
        raise ValueError("No documents to summarize")

    candidates = ranked
    if "mission" in normalized_question:
        mission_docs = [doc for doc in candidates if "mission" in _normalize(doc.title)]
        if mission_docs:
            candidates = mission_docs

    location_terms = [term for term in ["nimes", "nime", "france"] if term in normalized_question]
    expanded_terms = set(location_terms)
    if "nime" in expanded_terms:
        expanded_terms.add("nimes")
    if "nimes" in expanded_terms:
        expanded_terms.add("france")
    if location_terms:
        location_docs = [
            doc
            for doc in candidates
            if any(term in _normalize(f"{doc.title} {doc.snippet}") for term in expanded_terms)
        ]
        if location_docs:
            candidates = location_docs

    return candidates[0]
