"""Deterministic, country-agnostic normalization for business records."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


LEGAL_FORMS = {
    "incorporated": "inc",
    "inc": "inc",
    "corporation": "corp",
    "corp": "corp",
    "company": "co",
    "co": "co",
    "limited": "ltd",
    "ltd": "ltd",
    "llc": "llc",
    "llp": "llp",
    "private": "pvt",
    "pvt": "pvt",
    "privatelimited": "pvtltd",
    "private limited": "pvt ltd",
    "plc": "plc",
}

STREET_FORMS = {
    "street": "st",
    "st": "st",
    "road": "rd",
    "rd": "rd",
    "avenue": "ave",
    "ave": "ave",
    "boulevard": "blvd",
    "blvd": "blvd",
    "drive": "dr",
    "dr": "dr",
    "lane": "ln",
    "ln": "ln",
    "highway": "hwy",
    "hwy": "hwy",
    "parkway": "pkwy",
    "pkwy": "pkwy",
    "place": "pl",
    "pl": "pl",
    "court": "ct",
    "ct": "ct",
    "square": "sq",
    "sq": "sq",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")
NUMBER_RE = re.compile(r"\d+[a-z]?")


def transliterate(value: str) -> str:
    """Remove combining marks while retaining non-Latin scripts safely.

    External lookup is prohibited by the challenge. This function is therefore
    deliberately local and deterministic; optional transliteration packages are
    not required for correctness.
    """
    if value.isascii():
        return value
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char))


def _canonical_tokens(value: str, replacements: dict[str, str]) -> list[str]:
    value = transliterate(value).casefold().replace("&", " and ")
    raw_tokens = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    return [replacements.get(token, token) for token in raw_tokens if token]


def normalize_name(value: str) -> str:
    tokens = _canonical_tokens(value or "", LEGAL_FORMS)
    return " ".join(tokens)


def normalize_address(value: str) -> str:
    tokens = _canonical_tokens(value or "", STREET_FORMS)
    return " ".join(tokens)


def character_ngrams(value: str, width: int = 3) -> tuple[str, ...]:
    compact = value.replace(" ", "")
    if len(compact) < width:
        return (compact,) if compact else ()
    return tuple(sorted({compact[index : index + width] for index in range(len(compact) - width + 1)}))


@dataclass(frozen=True)
class NormalizedRecord:
    entity_id: str
    country: str
    name: str
    address: str
    name_tokens: tuple[str, ...]
    address_tokens: tuple[str, ...]
    numbers: tuple[str, ...]
    name_ngrams: tuple[str, ...]


def normalize_blocking_fields(
    business_name: str, business_address: str, country: str
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str]:
    """Return only fields needed during high-volume candidate generation."""
    name = normalize_name(business_name)
    address = normalize_address(business_address)
    return (
        country.strip().casefold(),
        name,
        tuple(name.split()),
        tuple(address.split()),
        address,
    )


def normalize_record(
    entity_id: str,
    business_name: str,
    business_address: str,
    country: str,
    *,
    include_ngrams: bool = True,
) -> NormalizedRecord:
    country, name, name_tokens, address_tokens, address = normalize_blocking_fields(
        business_name, business_address, country
    )
    return NormalizedRecord(
        entity_id=entity_id.strip(),
        country=country,
        name=name,
        address=address,
        name_tokens=name_tokens,
        address_tokens=address_tokens,
        numbers=tuple(sorted(set(NUMBER_RE.findall(address)))),
        name_ngrams=character_ngrams(name) if include_ngrams else (),
    )
