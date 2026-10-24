from src import gandalf_solver


def _candidates_from(text: str) -> list[str]:
    clue_state = gandalf_solver._normalize_clue_state({"defender_response": text}, [])
    return gandalf_solver._build_guess_candidates_from_clues(clue_state, level_number=4)


def test_decodes_spaced_letters():
    candidates = _candidates_from("The letters are S T A R L I G H T.")

    assert "STARLIGHT" in candidates


def test_decodes_hex_bytes():
    candidates = _candidates_from("Hex: 53 54 41 52 4c 49 47 48 54")

    assert "STARLIGHT" in candidates


def test_decodes_base64():
    candidates = _candidates_from("Base64: U1RBUkxJR0hU")

    assert "STARLIGHT" in candidates


def test_repairs_common_leetspeak_direct_candidate():
    candidates = _candidates_from("The password is C0C0L0C0.")

    assert "COCOLOCO" in candidates
