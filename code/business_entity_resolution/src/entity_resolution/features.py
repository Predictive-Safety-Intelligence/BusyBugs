"""Pairwise features for candidate business-record matches."""

from __future__ import annotations

from collections.abc import Iterable

from rapidfuzz import fuzz

from .normalize import NormalizedRecord


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _containment(left: Iterable[str], right: Iterable[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set:
        return 0.0
    return len(left_set & right_set) / len(left_set)


def pair_features(source: NormalizedRecord, target: NormalizedRecord) -> dict[str, float]:
    """Compute bounded numeric features for one Source 1/target pair."""
    name_ratio = fuzz.ratio(source.name, target.name) / 100.0
    address_ratio = fuzz.ratio(source.address, target.address) / 100.0
    return {
        "country_equal": float(source.country == target.country),
        "name_ratio": name_ratio,
        "name_token_set_ratio": fuzz.token_set_ratio(source.name, target.name) / 100.0,
        "name_token_sort_ratio": fuzz.token_sort_ratio(source.name, target.name) / 100.0,
        "name_partial_ratio": fuzz.partial_ratio(source.name, target.name) / 100.0,
        "name_token_jaccard": _jaccard(source.name_tokens, target.name_tokens),
        "name_source_containment": _containment(source.name_tokens, target.name_tokens),
        "name_target_containment": _containment(target.name_tokens, source.name_tokens),
        "address_ratio": address_ratio,
        "address_token_set_ratio": fuzz.token_set_ratio(source.address, target.address) / 100.0,
        "address_token_sort_ratio": fuzz.token_sort_ratio(source.address, target.address) / 100.0,
        "address_token_jaccard": _jaccard(source.address_tokens, target.address_tokens),
        "address_source_containment": _containment(source.address_tokens, target.address_tokens),
        "address_target_containment": _containment(target.address_tokens, source.address_tokens),
        "number_jaccard": _jaccard(source.numbers, target.numbers),
        "number_source_containment": _containment(source.numbers, target.numbers),
        "number_target_containment": _containment(target.numbers, source.numbers),
        "name_exact": float(source.name == target.name and bool(source.name)),
        "address_exact": float(source.address == target.address and bool(source.address)),
    }
