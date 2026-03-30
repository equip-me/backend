import re

from app.core.identifiers import SHORT_ID_ALPHABET, SHORT_ID_LENGTH, generate_short_id

_VALID_PATTERN = re.compile(r"^[A-Z0-9]+$")


def test_generate_short_id_default_length() -> None:
    result = generate_short_id()
    assert len(result) == SHORT_ID_LENGTH


def test_generate_short_id_custom_length() -> None:
    for length in (4, 8, 12):
        result = generate_short_id(length)
        assert len(result) == length


def test_generate_short_id_valid_characters() -> None:
    for _ in range(100):
        result = generate_short_id()
        assert _VALID_PATTERN.match(result), f"Invalid character in {result}"


def test_generate_short_id_uniqueness() -> None:
    ids = {generate_short_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_short_id_alphabet_is_uppercase_alphanumeric() -> None:
    assert SHORT_ID_ALPHABET == "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    assert len(SHORT_ID_ALPHABET) == 36
