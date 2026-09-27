"""Measure indexed blocking recall against known training links."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from entity_resolution.index import retrieve_candidates
from entity_resolution.normalize import normalize_blocking_fields


def load_truth(path: Path, limit: int) -> dict[str, set[str]]:
    truth = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            truth[row["source1_entity_id"]] = {
                value.strip() for value in row["matched_entity_ids"].split(",") if value.strip()
            }
            if len(truth) >= limit:
                break
    return truth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    truth = load_truth(args.dataset / "train" / "train_ground_truth.tsv", args.limit)
    connection = sqlite3.connect(args.index)
    recovered = total = complete = processed = 0
    with (args.dataset / "train" / "train_source1.tsv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["entity_id"] not in truth:
                continue
            country, name, name_tokens, address_tokens, address = normalize_blocking_fields(
                row["business_name"], row["business_address"], row["country"]
            )
            candidates = set(
                retrieve_candidates(
                    connection, country, name, name_tokens, address, address_tokens
                )
            )
            actual = truth[row["entity_id"]]
            recovered += len(actual & candidates)
            total += len(actual)
            complete += actual.issubset(candidates)
            processed += 1
            if processed == len(truth):
                break
    connection.close()
    print(json.dumps({
        "entities": len(truth),
        "processed_entities": processed,
        "true_links": total,
        "recovered_links": recovered,
        "link_recall": recovered / total if total else 0.0,
        "complete_entities": complete,
        "entity_recall": complete / len(truth) if truth else 0.0,
    }, indent=2))


if __name__ == "__main__":
    main()
