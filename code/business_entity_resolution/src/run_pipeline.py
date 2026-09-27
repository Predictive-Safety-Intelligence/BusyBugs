"""Reproducible test inference for the Business Entity Resolution challenge.

The pipeline expects a DuckDB index created by build_duckdb_index.py. It performs
country-aware blocking in DuckDB, scores only retrieved pairs, and writes both
required TSV files incrementally.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import duckdb
from rapidfuzz import fuzz

from entity_resolution.normalize import NormalizedRecord, normalize_record


def score(source, target) -> float:
    name = fuzz.token_set_ratio(source.name, target.name) / 100
    address = fuzz.token_set_ratio(source.address, target.address) / 100
    exact_name = bool(source.name) and source.name == target.name
    exact_address = bool(source.address) and source.address == target.address
    number_overlap = bool(set(source.numbers) & set(target.numbers))
    if exact_name and (exact_address or not target.address or not source.address):
        return 1.0
    if exact_address and name >= 0.55:
        return 0.99
    if name >= 0.93 and address >= 0.78:
        return 0.97
    if name >= 0.97 and (number_overlap or address >= 0.60):
        return 0.95
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--max-source1", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=0.95)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    split = "test"
    source_path = args.dataset / split / "test_source1.tsv"
    matching_path = args.output / "matching_results.tsv"
    candidate_path = args.output / "candidate_pairs.tsv"
    con = duckdb.connect(str(args.index), read_only=True)

    with source_path.open(encoding="utf-8", newline="") as source_handle, \
            matching_path.open("w", encoding="utf-8", newline="") as match_handle, \
            candidate_path.open("w", encoding="utf-8", newline="") as candidate_handle:
        reader = csv.DictReader(source_handle, delimiter="\t")
        match_writer = csv.writer(match_handle, delimiter="\t", lineterminator="\n")
        candidate_writer = csv.writer(candidate_handle, delimiter="\t", lineterminator="\n")
        match_writer.writerow(["source1_entity_id", "matched_entity_ids"])
        candidate_writer.writerow(["source1_entity_id", "candidate_entity_ids"])

        processed = 0
        while True:
            rows = []
            for _ in range(args.batch_size):
                if args.max_source1 is not None and processed + len(rows) >= args.max_source1:
                    break
                try:
                    rows.append(next(reader))
                except StopIteration:
                    break
            if not rows:
                break
            processed += len(rows)

            source_records = {
                row["entity_id"]: normalize_record(
                    row["entity_id"], row["business_name"], row["business_address"], row["country"],
                    include_ngrams=False,
                )
                for row in rows
            }
            con.execute("CREATE OR REPLACE TEMP TABLE source1(entity_id VARCHAR, country VARCHAR, name VARCHAR, address VARCHAR)")
            con.executemany(
                "INSERT INTO source1 VALUES (?, ?, ?, ?)",
                [(r.entity_id, r.country, r.name, r.address) for r in source_records.values()],
            )
            pairs = con.execute(
                """
                WITH source_keys AS (
                    SELECT entity_id, country, 'name_exact' AS key_type, name AS key_value
                    FROM source1 WHERE name <> ''
                    UNION ALL
                    SELECT entity_id, country, 'address_exact', address
                    FROM source1 WHERE address <> ''
                    UNION ALL
                    SELECT s.entity_id, s.country, 'name_token', t.token
                    FROM source1 s, UNNEST(string_split(s.name, ' ')) AS t(token)
                    WHERE length(t.token) >= 4
                    UNION ALL
                    SELECT s.entity_id, s.country, 'address_token', t.token
                    FROM source1 s, UNNEST(string_split(s.address, ' ')) AS t(token)
                    WHERE length(t.token) >= 4
                )
                SELECT DISTINCT sk.entity_id, tr.entity_id, tr.country, tr.name, tr.address
                FROM source_keys sk
                JOIN keys k USING (country, key_type, key_value)
                JOIN target_records tr ON tr.entity_id = k.entity_id
                """
            ).fetchall()
            candidates = {entity_id: set() for entity_id in source_records}
            target_records = {}
            for source_id, target_id, country, name, address in pairs:
                candidates[source_id].add(target_id)
                if target_id not in target_records:
                    target_records[target_id] = normalize_record(
                        target_id, name, address, country, include_ngrams=False
                    )
            for source_id, source in source_records.items():
                ids = sorted(candidates[source_id])
                matched = [
                    target_id for target_id in ids
                    if score(source, target_records[target_id]) >= args.threshold
                ]
                candidate_writer.writerow([source_id, ",".join(ids)])
                match_writer.writerow([source_id, ",".join(matched)])
    con.close()


if __name__ == "__main__":
    main()
