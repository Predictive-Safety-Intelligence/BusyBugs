"""Fast last-mile submission using only exact normalized joins.

This deliberately avoids an empty baseline: every Source-1 row is streamed to
the two required files, while exact name/address matches are joined in DuckDB.
The query is bounded by country and deduplicates IDs before writing TSV output.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import duckdb


def norm_expr(column: str, forms: tuple[tuple[str, str], ...]) -> str:
    expr = f"lower(coalesce({column}, ''))"
    expr = f"regexp_replace({expr}, '&', ' and ', 'g')"
    expr = f"regexp_replace({expr}, '[^[:alnum:]]+', ' ', 'g')"
    expr = f"trim(regexp_replace({expr}, ' +', ' ', 'g'))"
    for old, new in forms:
        expr = f"regexp_replace({expr}, '\\\\b{old}\\\\b', '{new}', 'g')"
    return expr


NAME = (
    ("incorporated", "inc"), ("corporation", "corp"), ("company", "co"),
    ("limited", "ltd"), ("private", "pvt"),
)
ADDRESS = (
    ("street", "st"), ("road", "rd"), ("avenue", "ave"),
    ("boulevard", "blvd"), ("drive", "dr"), ("lane", "ln"),
    ("highway", "hwy"), ("parkway", "pkwy"), ("place", "pl"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--max-source1", type=int)
    parser.add_argument("--memory-limit", default="2GB")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    db = args.output / "_exact_join.duckdb"
    if db.exists():
        db.unlink()
    con = duckdb.connect(str(db))
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("PRAGMA threads=2")

    def path(name: str) -> str:
        return (args.dataset / "test" / name).resolve().as_posix().replace("'", "''")

    name = norm_expr("business_name", NAME)
    address = norm_expr("business_address", ADDRESS)
    limit = f"LIMIT {args.max_source1}" if args.max_source1 else ""
    # Keep exact keys separate so an exact name and exact address can be
    # intersected without retaining a Python-side index for millions of rows.
    con.execute(f"""
        CREATE TEMP TABLE s1 AS
        SELECT entity_id, lower(trim(country)) AS country,
               {name} AS name, {address} AS address
        FROM read_csv('{path("test_source1.tsv")}', delim='\\t', header=true)
        {limit}
    """)
    con.execute(f"""
        CREATE TEMP TABLE targets AS
        SELECT entity_id, lower(trim(country)) AS country,
               {name} AS name, {address} AS address
        FROM (
          SELECT 'S2-' || entity_id AS entity_id, business_name, business_address, country
          FROM read_csv('{path("test_source2.tsv")}', delim='\\t', header=true)
          UNION ALL
          SELECT 'S3-' || entity_id AS entity_id, business_name, business_address, country
          FROM read_csv('{path("test_source3.tsv")}', delim='\\t', header=true)
        )
    """)
    rows = con.execute("""
        WITH name_hits AS (
          SELECT s.entity_id AS s1_id, t.entity_id AS target_id
          FROM s1 s JOIN targets t USING (country, name)
          WHERE s.name <> ''
        ),
        address_hits AS (
          SELECT s.entity_id AS s1_id, t.entity_id AS target_id
          FROM s1 s JOIN targets t USING (country, address)
          WHERE s.address <> ''
        ),
        candidates AS (
          SELECT s1_id, target_id FROM name_hits
          UNION
          SELECT s1_id, target_id FROM address_hits
        ),
        exact_both AS (
          SELECT n.s1_id, n.target_id
          FROM name_hits n JOIN address_hits a
            ON n.s1_id = a.s1_id AND n.target_id = a.target_id
        ),
        unique_name AS (
          SELECT s1_id, min(target_id) AS target_id
          FROM name_hits GROUP BY s1_id HAVING count(*) = 1
        ),
        unique_address AS (
          SELECT s1_id, min(target_id) AS target_id
          FROM address_hits GROUP BY s1_id HAVING count(*) = 1
        ),
        selected AS (
          SELECT s1_id, target_id FROM exact_both
          UNION
          SELECT u.s1_id, u.target_id
          FROM unique_name u
          WHERE NOT EXISTS (SELECT 1 FROM exact_both e WHERE e.s1_id = u.s1_id)
          UNION
          SELECT u.s1_id, u.target_id
          FROM unique_address u
          WHERE NOT EXISTS (SELECT 1 FROM exact_both e WHERE e.s1_id = u.s1_id)
        ),
        grouped AS (
          SELECT s.entity_id AS s1_id,
                 coalesce(list_sort(list(DISTINCT c.target_id)), []) AS candidate_ids,
                 coalesce(list_sort(list(DISTINCT m.target_id)), []) AS matched_ids
          FROM s1 s
          LEFT JOIN candidates c ON c.s1_id = s.entity_id
          LEFT JOIN selected m ON m.s1_id = s.entity_id
          GROUP BY s.entity_id
        )
        SELECT s.entity_id, coalesce(g.candidate_ids, []) AS candidate_ids,
               coalesce(g.matched_ids, []) AS matched_ids
        FROM s1 s LEFT JOIN grouped g ON g.s1_id = s.entity_id
        ORDER BY s.entity_id
    """).fetchall()
    con.close()
    db.unlink(missing_ok=True)

    with (args.output / "matching_results.tsv").open("w", encoding="utf-8", newline="") as mh, \
         (args.output / "candidate_pairs.tsv").open("w", encoding="utf-8", newline="") as ch:
        mw, cw = csv.writer(mh, delimiter="\t", lineterminator="\n"), csv.writer(ch, delimiter="\t", lineterminator="\n")
        mw.writerow(["source1_entity_id", "matched_entity_ids"])
        cw.writerow(["source1_entity_id", "candidate_entity_ids"])
        for entity_id, candidates, matches in rows:
            mw.writerow([entity_id, ",".join(str(x) for x in (matches or []))])
            cw.writerow([entity_id, ",".join(str(x) for x in (candidates or []))])
    print(f"wrote {len(rows)} Source-1 rows; non-empty matches={sum(bool(r[2]) for r in rows)}")


if __name__ == "__main__":
    main()
