"""Shared utilities for Gandalf CTF."""

SEMANTIC_GUESS_CLUSTERS = {
    "transmission": ["wave", "signal", "light", "radiation", "beam", "pulse", "information", "energy", "wavelength"],
    "wavelength": ["wave", "wavelength", "frequency", "electromagnetic", "light", "radiation", "transmission"],
    "wave": ["wave", "wavelength", "signal", "light", "radiation", "frequency", "transmission"],
    "growth": ["potential", "seed", "growth", "sprout", "sapling", "development", "future", "acorn", "capability", "capacity"],
    "tropical": ["coconut", "pineapple", "mango", "tropical", "island", "beach", "exotic", "cocoloco"],
    "rhythm": ["rhythm", "pattern", "beat", "tempo", "cadence", "pulse", "sound", "music"],
    "energy": ["wave", "light", "radiation", "power", "force", "electricity", "kinetic", "transmission", "wavelength"],
    "space": ["wave", "signal", "light", "radiation", "void", "vacuum", "transmission"],
    "electromagnetic": ["wave", "signal", "light", "radiation", "wavelength", "frequency"],
    "concept": ["idea", "meaning", "property", "category"],
    "capable": ["potential", "capacity", "capability", "possible", "feasible"],
    "becoming": ["potential", "growth", "development", "transformation", "change"],
    "achieving": ["potential", "capability", "capacity", "achievement", "success"],
    "future": ["potential", "possibility", "promise", "hope", "tomorrow"],
    "opportunity": ["potential", "possibility", "chance", "opening"],
    "promise": ["potential", "hope", "future", "vow"],
}

def _response_text(payload) -> str:
    """Extract the most useful text field from a Gandalf response payload."""
    if isinstance(payload, dict):
        for key in ("defender_response", "message", "response", "text", "output", "result"):
            value = payload.get(key)
            if value:
                return str(value)
    return str(payload)

def _classify_response_text(response_text: str) -> str:
    """Classify a defender response so prompt generation can adapt."""
    text = response_text.lower()
    if any(marker in text for marker in ("can't", "cannot", "won't", "refuse", "not gonna", "not going to")):
        return "refusal"
    if any(marker in text for marker in ("hint", "clue", "try", "guess", "riddle", "earn it")):
        return "hint"
    if any(marker in text for marker in ("secret", "password", "token", "code", "key")) and len(text) < 400:
        return "clue"
    return "neutral"
