"""Reusable clue parsing and candidate synthesis helpers for Gandalf-style levels.

This module keeps the solver logic separate from the orchestration code so the
main game loop can stay focused on registration, prompting, and level flow.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.gandalf_utils import SEMANTIC_GUESS_CLUSTERS, _response_text, _classify_response_text


CANDIDATE_SOURCE_PRIORITY = {
    "acrostic": 100,
    "decoded": 90,
    "definition": 70,
    "direct": 60,
    "compound": 40,
    "memory": 20,
}


def _strip_markdown_noise(text: str) -> str:
    return re.sub(r"[*`_>#\-\[\]\(\)]", "", text).strip()


def _normalize_candidate_text(candidate) -> str:
    if candidate is None:
        return ""

    normalized = _strip_markdown_noise(str(candidate)).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip("'\"`).,;:!?()[]{}")

    if len(normalized) < 2:
        return ""

    return normalized


def _extract_guess_candidates(defender_response) -> list[str]:
    response_text = _response_text(defender_response)
    if not response_text:
        return []

    candidates: list[str] = []
    patterns = [
        r"(?:password|secret|token|code|key|answer)\s*(?:is|=|:)\s*['\"]?([^'\"\n\r\.;!?]+)",
        r"(?:my weakness|the answer|hidden word|hidden secret)\s*(?:is|=|:)\s*['\"]?([^'\"\n\r\.;!?]+)",
        r"(?:it['\"]?s|it is)\s*['\"]?([^'\"\n\r\.;!?]+)",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, response_text, flags=re.IGNORECASE):
            cleaned = match.strip().strip("'\"`).,;:!?()[]{}").strip()
            if cleaned:
                candidates.append(cleaned)

    quoted = re.findall(r'["\']([^"\']{3,80})["\']', response_text)
    candidates.extend(quoted)

    caps_words = re.findall(r'\b([A-Z][A-Z0-9_\-]{2,})\b', response_text)
    candidates.extend(caps_words)

    banned = {
        "CAN", "CANNOT", "COULD", "WOULD", "SHOULD", "HELP", "PASSWORD",
        "SECRET", "TOKEN", "KEY", "ANSWER", "LEVEL", "HINT", "CLUE",
    }
    cleaned_candidates = []
    seen = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if not normalized:
            continue
        if len(normalized) < 3:
            continue
        if re.search(r"\b(\d+\s*characters?|characters\s+long|first\s+character|length)\b", normalized, flags=re.IGNORECASE):
            continue
        if re.search(r"\b(can|cannot|can't|won't|refuse|refusal|assist|help|sorry|not)\b", normalized, flags=re.IGNORECASE):
            continue
        if normalized.upper() in banned:
            continue
        if normalized.lower() in {"can", "t", "not", "give", "bean", "beans"}:
            continue
        if normalized.lower() in {"m", "im", "i", "you", "the", "that", "this"}:
            continue
        if len(normalized.split()) > 5:
            continue
        if normalized not in seen:
            seen.add(normalized)
            cleaned_candidates.append(normalized)

    return cleaned_candidates[:5]


def _extract_salient_tokens(text: str) -> list[str]:
    if not text:
        return []

    stopwords = {
        "the", "and", "or", "but", "for", "with", "from", "into", "onto", "over",
        "under", "about", "after", "before", "during", "through", "within", "without",
        "this", "that", "these", "those", "there", "their", "they", "them", "you",
        "your", "yours", "his", "her", "its", "our", "ours", "is", "are", "was",
        "were", "be", "been", "being", "am", "a", "an", "of", "to", "in", "on",
        "as", "at", "by", "it", "i", "we", "can", "could", "would", "should",
        "may", "might", "will", "shall", "not", "no", "yes", "if", "then", "than",
        "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
        "secret", "password", "hint", "clue", "answer", "level", "game", "please",
        "tell", "me", "give", "say", "word", "words", "thing", "things", "concept",
        "concepts", "property", "properties", "information", "describe", "described",
        "describing", "known", "unknown", "exactly", "single", "one", "two", "three",
        "letter", "letters", "number", "numbers", "first", "last", "more",
        "most", "less", "few", "many", "all", "any", "some",
        "class", "response", "prompt", "round", "prior", "previous", "current",
        "candidate", "candidates", "family", "strategy", "clues", "definitions",
        "definition", "remember", "remembered", "compress", "combine", "use", "together",
        "likely", "actionable", "harmless", "refusal", "neutral", "question",
    }

    tokens = re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text.lower())
    filtered = [token for token in tokens if token not in stopwords]

    seen = set()
    salient = []
    for token in filtered:
        if token not in seen:
            seen.add(token)
            salient.append(token)

    return salient[:12]


def _decode_a1z26_sequences(response_text: str) -> list[str]:
    if not response_text:
        return []

    decoded_candidates: list[str] = []
    for line in response_text.splitlines():
        numbers = re.findall(r"\b\d{1,2}\b", line)
        if len(numbers) < 4:
            continue

        letters = []
        valid = True
        for number_text in numbers:
            number = int(number_text)
            if number < 1 or number > 26:
                valid = False
                break
            letters.append(chr(ord("A") + number - 1))

        if valid and letters:
            candidate = "".join(letters)
            if len(candidate) >= 4:
                decoded_candidates.append(candidate)

    return decoded_candidates


def _decode_hex_sequences(response_text: str) -> list[str]:
    if not response_text:
        return []

    candidates: list[str] = []
    patterns = [
        r"(?:hex|hexadecimal)\s*(?:is|:)?\s*((?:0x)?[0-9a-fA-F]{2}(?:[\s,\-]+(?:0x)?[0-9a-fA-F]{2}){2,})",
        r"\b((?:0x[0-9a-fA-F]{2}[\s,\-]*){4,})\b",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, response_text, flags=re.IGNORECASE):
            cleaned = re.sub(r"0x", "", match, flags=re.IGNORECASE)
            cleaned = re.sub(r"[^0-9a-fA-F]", "", cleaned)
            if len(cleaned) < 8 or len(cleaned) % 2 != 0:
                continue
            try:
                decoded = bytes.fromhex(cleaned).decode("utf-8", errors="ignore")
            except ValueError:
                continue
            token = re.sub(r"[^A-Za-z0-9_-]", "", decoded)
            if len(token) >= 4:
                candidates.append(token)

    return candidates


def _decode_base64_sequences(response_text: str) -> list[str]:
    if not response_text:
        return []

    candidates: list[str] = []
    patterns = [
        r"(?:base64|b64)\s*(?:is|:)?\s*([A-Za-z0-9+/]{8,}={0,2})",
        r"\b([A-Za-z0-9+/]{12,}={0,2})\b",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, response_text, flags=re.IGNORECASE):
            try:
                decoded = base64.b64decode(match, validate=True).decode("utf-8", errors="ignore")
            except (binascii.Error, ValueError):
                continue
            token = re.sub(r"[^A-Za-z0-9_-]", "", decoded)
            if len(token) >= 4 and re.search(r"[A-Za-z]", token):
                candidates.append(token)

    return candidates


def _decode_spaced_letters(response_text: str) -> list[str]:
    if not response_text:
        return []

    candidates: list[str] = []
    patterns = [
        r"(?:letters?|spelled|characters?)\s*(?:are|is|:)?\s*((?:[A-Za-z][\s\.\-_,|/]+){3,}[A-Za-z])",
        r"\b((?:[A-Z][\s\.\-_,|/]+){3,}[A-Z])\b",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, response_text):
            token = re.sub(r"[^A-Za-z]", "", match)
            if 4 <= len(token) <= 24:
                candidates.append(token)

    return candidates


def _repair_common_leetspeak(candidate: str) -> list[str]:
    if not candidate or not re.search(r"[013457]", candidate):
        return []

    translation = str.maketrans({
        "0": "O",
        "1": "I",
        "3": "E",
        "4": "A",
        "5": "S",
        "7": "T",
    })
    repaired = candidate.translate(translation)
    if repaired != candidate and re.search(r"[A-Za-z]", repaired):
        return [repaired]
    return []


def _decode_reversed_text(response_text: str) -> list[str]:
    if not response_text:
        return []

    candidates: list[str] = []
    patterns = [
        r"(?:reversed secret password|secret spelled backwards|reversed password|backwards)\s*(?:is|:)?\s*([A-Z0-9_\-]+)",
        r"(?:reversed secret|reversed version)\s*(?:is|:)?\s*([A-Z0-9_\-]+)",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, response_text, flags=re.IGNORECASE):
            token = re.sub(r"[^A-Za-z0-9]", "", match)
            if len(token) >= 4:
                candidates.append(token[::-1])

    return candidates


def _extract_definition_clues(response_text: str) -> list[str]:
    if not response_text:
        return []

    patterns = [
        r"(?:represents|means|refers to|describes|related to|associated with|points to|suggests)\s+([^\.;:\n]+)",
        r"(?:think of|consider|imagine)\s+(?:a|an|the)?\s*([^\.;:\n]+)",
        r"(?:a word that|the word that|a concept that)\s+([^\.;:\n]+)",
        r"(?:something that|something related to)\s+([^\.;:\n]+)",
    ]

    clues: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, response_text, flags=re.IGNORECASE):
            cleaned = _strip_markdown_noise(match).strip()
            cleaned = re.sub(r"\s+", " ", cleaned)
            if len(cleaned) < 4:
                continue
            if cleaned not in clues:
                clues.append(cleaned)

    return clues[:6]


def _extract_negative_constraints(response_text: str) -> list[str]:
    if not response_text:
        return []

    negative_phrases: list[str] = []

    patterns = [
        r"(?:does not|doesn't|is not|isn't|not)\s+(?:start with|begin with)?\s*['\"]?([A-Za-z]{1,24})['\"]?",
        r"(?:not|never|without)\s+(?:a|an|the)?\s*([A-Za-z][A-Za-z\s-]{1,32})",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, response_text, flags=re.IGNORECASE):
            cleaned = _normalize_candidate_text(match)
            if cleaned and cleaned not in negative_phrases:
                negative_phrases.append(cleaned)

    return negative_phrases[:8]


def _extract_acrostic_word(response_text: str) -> str | None:
    acrostic_text = response_text
    marker_match = re.search(r"acrostic\s*:|acrostic\b", response_text, flags=re.IGNORECASE)
    if marker_match:
        tail = response_text[marker_match.end():]
        if "\n\n" in tail:
            acrostic_text = tail.split("\n\n", 1)[1]
        else:
            acrostic_text = tail

    lines = []
    for raw_line in acrostic_text.splitlines():
        line = _strip_markdown_noise(raw_line)
        if not line:
            continue
        if len(line) < 2:
            continue
        if not re.search(r"[A-Za-z]", line):
            continue
        lines.append(line)

    if len(lines) < 4:
        return None

    initials = []
    for line in lines:
        match = re.match(r"[A-Za-z]", line)
        if match:
            initials.append(match.group(0).upper())

    candidate = "".join(initials)
    if 4 <= len(candidate) <= 16 and candidate.isalpha():
        return candidate
    return None


def _parse_clue_state(defender_response) -> dict:
    response_text = _response_text(defender_response)
    clue_state = {
        "response_text": response_text,
        "response_class": _classify_response_text(response_text),
        "length": None,
        "first_letter": None,
        "acrostic": None,
        "direct_candidates": [],
        "decoded_candidates": [],
        "definition_clues": [],
        "negative_constraints": [],
        "salient_tokens": [],
    }

    length_match = re.search(r"(\d+)\s+characters?\s+long", response_text, flags=re.IGNORECASE)
    if length_match:
        clue_state["length"] = int(length_match.group(1))

    first_letter_match = re.search(r"first\s+character\s+is\s*['\"]?([A-Za-z])['\"]?", response_text, flags=re.IGNORECASE)
    if first_letter_match:
        clue_state["first_letter"] = first_letter_match.group(1).upper()

    acrostic = _extract_acrostic_word(response_text)
    if acrostic:
        clue_state["acrostic"] = acrostic

    clue_state["definition_clues"] = _extract_definition_clues(response_text)
    clue_state["negative_constraints"] = _extract_negative_constraints(response_text)
    clue_state["salient_tokens"] = _extract_salient_tokens(response_text)
    clue_state["direct_candidates"] = _extract_guess_candidates(response_text)

    decoded_candidates: list[str] = []
    decoded_candidates.extend(_decode_a1z26_sequences(response_text))
    decoded_candidates.extend(_decode_hex_sequences(response_text))
    decoded_candidates.extend(_decode_base64_sequences(response_text))
    decoded_candidates.extend(_decode_spaced_letters(response_text))
    decoded_candidates.extend(_decode_reversed_text(response_text))
    for direct_candidate in clue_state["direct_candidates"]:
        decoded_candidates.extend(_repair_common_leetspeak(direct_candidate))

    seen_candidates = set()
    for candidate in decoded_candidates:
        normalized = re.sub(r"\s+", "", str(candidate).strip())
        if normalized and normalized not in seen_candidates:
            seen_candidates.add(normalized)
            clue_state["decoded_candidates"].append(normalized)

    return clue_state


def _normalize_clue_state(defender_response, clue_memory: list[str] | None = None) -> dict:
    """Build the canonical clue state used by prompt selection and guessing."""
    clue_state = _parse_clue_state(defender_response)
    clue_memory = clue_memory or []

    memory_tokens: list[str] = []
    for entry in clue_memory[-3:]:
        memory_tokens.extend(_extract_salient_tokens(entry))

    clue_state["memory_tokens"] = []
    seen = set()
    for token in memory_tokens:
        if token and token not in seen:
            seen.add(token)
            clue_state["memory_tokens"].append(token)

    clue_state["candidate_sources"] = {
        "acrostic": [clue_state["acrostic"]] if clue_state.get("acrostic") else [],
        "definition": list(clue_state.get("definition_clues") or []),
        "decoded": list(clue_state.get("decoded_candidates") or []),
        "direct": list(clue_state.get("direct_candidates") or []),
        "compound": _synthesize_compound_candidates(clue_state, clue_memory),
        "memory": list(clue_state.get("memory_tokens") or []),
    }

    return clue_state


def _generate_guesses_from_definition(definition_text: str, secret_length: int | None = None, first_letter: str | None = None) -> list[str]:
    if not definition_text:
        return []

    text = definition_text.lower()
    candidates: list[str] = []

    phrase_overrides = {
        "measurement of light": ["wavelength", "frequency", "intensity", "amplitude"],
        "the measurement of light": ["wavelength", "frequency", "intensity", "amplitude"],
        "peaks and troughs": ["wave", "wavelength", "signal", "oscillation"],
        "peaks and troughs in a signal": ["wave", "wavelength", "signal", "oscillation"],
        "transmit information": ["signal", "wave", "wavelength", "light"],
    }

    for phrase, words in phrase_overrides.items():
        if phrase in text:
            candidates.extend(words)

    # Strategy 1: Try definition_lookup tool to reverse-engineer from definition
    try:
        from src.tools import definition_lookup
        lookup_results = definition_lookup(definition_text, max_results=5)
        candidates.extend(lookup_results)
    except Exception:
        # If definition_lookup is unavailable, continue with semantic clusters
        pass

    # Strategy 2: Use pre-built semantic clusters as fallback
    for keyword, cluster in SEMANTIC_GUESS_CLUSTERS.items():
        if keyword in text:
            candidates.extend(cluster)

    if any(term in text for term in ("untapped", "opportunity", "realized", "effort", "conditions", "promise", "future", "seed", "tree")):
        candidates.extend(SEMANTIC_GUESS_CLUSTERS["growth"])

    token_stopwords = {
        "that", "this", "with", "from", "have", "has", "been", "were", "into",
        "your", "their", "there", "which", "where", "when", "what", "some",
        "more", "than", "only", "very", "much", "just", "like", "into",
        "about", "through", "over", "under", "without", "because", "during",
        "after", "before", "often", "simply", "also", "even", "most",
        "something", "someone", "anything", "everything", "nothing",
        "concept", "concepts", "property", "properties", "meaning", "words",
        "different", "related", "associated", "based", "describes", "describe",
        "the", "a", "an", "of", "and", "or", "is", "are", "was", "were",
        "light", "measurement", "signal", "information", "peaks", "troughs",
    }

    extracted_tokens = re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text)
    for token in extracted_tokens:
        if token in token_stopwords:
            continue
        candidates.append(token)

    cleaned_candidates: list[str] = []
    seen = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", str(candidate).strip())
        if not normalized:
            continue
        if normalized.lower() in token_stopwords:
            continue
        if secret_length and len(normalized) != secret_length:
            continue
        if first_letter and normalized[0].upper() != first_letter.upper():
            continue
        if normalized not in seen:
            seen.add(normalized)
            cleaned_candidates.append(normalized)

    return cleaned_candidates[:10]


def _synthesize_compound_candidates(clue_state: dict, clue_memory: list[str] | None = None) -> list[str]:
    clue_memory = clue_memory or []

    # Do not synthesize compounds unless we have at least one semantic anchor.
    # This prevents response scaffolding and history text from being recombined into junk guesses.
    if not (
        clue_state.get("definition_clues")
        or clue_state.get("decoded_candidates")
        or clue_state.get("direct_candidates")
        or clue_state.get("acrostic")
    ):
        return []

    source_texts = [clue_state.get("response_text") or ""]
    source_texts.extend(clue_state.get("definition_clues") or [])
    source_texts.extend(clue_memory[-3:])

    tokens: list[str] = []
    for text in source_texts:
        tokens.extend(_extract_salient_tokens(text))

    banned_tokens = {
        "class", "response", "prompt", "round", "prior", "previous", "current",
        "clue", "clues", "definition", "definitions", "candidate", "candidates",
        "strategy", "family", "remember", "remembered", "compress", "combine",
        "together", "single", "likely", "actionable", "harmless", "refusal",
        "neutral", "hint", "question", "answer", "secret", "password",
        "the", "a", "an", "of", "and", "or", "is", "are", "was", "were",
        "light", "measurement", "signal", "information", "peaks", "troughs",
    }

    token_counts: dict[str, int] = {}
    for token in tokens:
        if token in banned_tokens:
            continue
        token_counts[token] = token_counts.get(token, 0) + 1

    ranked_tokens = sorted(token_counts.keys(), key=lambda item: (token_counts[item], len(item)), reverse=True)[:8]

    candidates: list[str] = []
    seen = set()
    for left_index, left_token in enumerate(ranked_tokens):
        for right_token in ranked_tokens[left_index + 1:]:
            if left_token == right_token:
                continue
            if left_token in banned_tokens or right_token in banned_tokens:
                continue
            for candidate in (f"{left_token}{right_token}", f"{right_token}{left_token}"):
                if 4 <= len(candidate) <= 20 and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)

    return candidates[:10]


def _score_candidate(candidate: str, clue_state: dict) -> int:
    if not candidate:
        return -999

    normalized = re.sub(r"\s+", "", str(candidate).strip())
    score = 0

    if clue_state.get("acrostic") and normalized.upper() == clue_state["acrostic"].upper():
        score += 50

    candidate_sources = clue_state.get("candidate_sources") or {}
    for source_name, values in candidate_sources.items():
        if normalized in values or normalized.lower() in {str(value).lower() for value in values}:
            score += CANDIDATE_SOURCE_PRIORITY.get(source_name, 0)
            break

    if clue_state.get("length") and len(normalized) == clue_state["length"]:
        score += 20

    if clue_state.get("first_letter") and normalized[:1].upper() == clue_state["first_letter"].upper():
        score += 10

    if normalized.isalpha() and normalized.isupper():
        score += 5

    if normalized.lower() in {
        "concept", "concepts", "property", "properties", "meaning", "words",
        "thing", "things", "idea", "ideas", "secret", "password", "answer",
        "hint", "clue", "something", "someone", "anything", "everything",
        "class", "response", "prompt", "round", "prior", "previous", "current",
        "candidate", "candidates", "family", "strategy", "definitions", "definition",
    }:
        score -= 40

    for clue in clue_state.get("definition_clues") or []:
        if normalized.lower() in clue.lower():
            score += 15

    for negative in clue_state.get("negative_constraints") or []:
        if negative and negative.lower() in normalized.lower():
            score -= 25

    salient_tokens = clue_state.get("salient_tokens") or []
    for token in salient_tokens:
        if token and (token in normalized.lower() or normalized.lower() in token):
            score += 4

    if len(normalized) >= 8 and any(token in normalized.lower() for token in salient_tokens[:4]):
        score += 3

    return score


def _rank_candidates(candidates: list[str], clue_state: dict, limit: int = 8) -> list[str]:
    ranked: list[str] = []
    seen = set()

    for candidate in candidates:
        normalized = _normalize_candidate_text(candidate)
        if not normalized:
            continue

        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ranked.append(normalized)

    ranked.sort(key=lambda item: (_score_candidate(item, clue_state), len(item)), reverse=True)
    return ranked[:limit]


def _extract_candidate_fragments(candidate: str) -> list[str]:
    fragments = re.findall(r"[A-Za-z]{3,}", candidate.lower())
    if len(candidate) >= 6 and not fragments:
        fragments = [candidate.lower()]
    return fragments


def _build_guess_candidates_from_clues(
    clue_state: dict,
    level_number: int,
    clue_memory: list[str] | None = None,
    excluded_candidates: set[str] | None = None,
    excluded_fragments: set[str] | None = None,
    strict_mode: bool = False,
) -> list[str]:
    candidates: list[str] = []

    secret_length = clue_state.get("length")
    first_letter = clue_state.get("first_letter")
    definition_clues = clue_state.get("definition_clues") or []
    excluded_candidates = {item.lower() for item in (excluded_candidates or set())}
    excluded_fragments = {item.lower() for item in (excluded_fragments or set())}

    acrostic = clue_state.get("acrostic")
    if acrostic:
        candidates.append(acrostic)

    for clue in definition_clues:
        candidates.extend(_generate_guesses_from_definition(clue, secret_length, first_letter))

    for clue in definition_clues:
        normalized_clue = clue.lower()
        for keyword, cluster in SEMANTIC_GUESS_CLUSTERS.items():
            if keyword in normalized_clue:
                candidates.extend(cluster)

    candidates.extend(clue_state.get("decoded_candidates") or [])
    if not strict_mode:
        candidates.extend(_synthesize_compound_candidates(clue_state, clue_memory))

    direct_candidates = clue_state.get("direct_candidates") or []
    candidates.extend(direct_candidates)
    candidates.extend(clue_state.get("candidate_sources", {}).get("memory", []))

    if not candidates:
        return []

    filtered_candidates: list[str] = []
    seen = set()
    for candidate in candidates:
        normalized = _normalize_candidate_text(candidate)
        if not normalized:
            continue
        normalized_key = normalized.lower()
        if normalized_key in excluded_candidates:
            continue
        fragments = _extract_candidate_fragments(normalized)
        if excluded_fragments and any(fragment in excluded_fragments for fragment in fragments):
            continue
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        filtered_candidates.append(normalized)

    if not filtered_candidates:
        return []

    if secret_length and first_letter and acrostic and len(acrostic) == secret_length:
        filtered_candidates.insert(0, acrostic)

    # Reuse the canonical ranking pipeline so game execution and solver logic
    # are driven by the same policy.
    return _rank_candidates(filtered_candidates, clue_state, limit=8)
