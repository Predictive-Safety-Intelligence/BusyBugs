"""Benchmark batch candidate retrieval from a DuckDB blocking index."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb

from build_duckdb_index import normalized_expression


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--split", choices=("train", "test"), default="train")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--max-rows", type=int, default=1000)
    args = parser.parse_args()

    source_path = (args.dataset / args.split / f"{args.split}_source1.tsv").as_posix()
    name_expr = normalized_expression(
        "business_name",
        (("corporation", "corp"), ("company", "co"), ("incorporated", "inc"),
         ("limited", "ltd"), ("private", "pvt")),
    )
    address_expr = normalized_expression(
        "business_address",
        (("street", "st"), ("road", "rd"), ("avenue", "ave"), ("boulevard", "blvd"),
         ("drive", "dr"), ("lane", "ln"), ("highway", "hwy")),
    )

    started = time.perf_counter()
    con = duckdb.connect(str(args.index), read_only=True)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE source1 AS
        SELECT entity_id, lower(trim(country)) AS country,
               {name_expr} AS name,
               {address_expr} AS address
        FROM read_csv('{source_path}', delim='\\t', header=true,
                      quote='\"', escape='\"', ignore_errors=false)
        LIMIT {args.max_rows}
        """
    )
    counts = con.execute(
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
        ),
        pairs AS (
            SELECT DISTINCT sk.entity_id AS source1_entity_id, k.entity_id AS target_entity_id
            FROM source_keys sk
            JOIN keys k USING (country, key_type, key_value)
        ),
        per_source AS (
            SELECT source1_entity_id, count(*) AS candidates
            FROM pairs
            GROUP BY source1_entity_id
        )
        SELECT
            (SELECT count(*) FROM source1) AS source_entities,
            (SELECT count(*) FROM pairs) AS candidate_pairs,
            coalesce(avg(candidates), 0) AS mean_candidates,
            coalesce(quantile_cont(candidates, 0.50), 0) AS p50_candidates,
            coalesce(quantile_cont(candidates, 0.95), 0) AS p95_candidates,
            coalesce(max(candidates), 0) AS max_candidates
        FROM per_source
        """
    ).fetchone()
    con.close()
    print(json.dumps({
        "index": str(args.index),
        "split": args.split,
        "seconds": round(time.perf_counter() - started, 3),
        "source_entities": counts[0],
        "candidate_pairs": counts[1],
        "mean_candidates": round(float(counts[2]), 3),
        "p50_candidates": float(counts[3]),
        "p95_candidates": float(counts[4]),
        "max_candidates": counts[5],
    }, indent=2))


if __name__ == "__main__":
    main()
