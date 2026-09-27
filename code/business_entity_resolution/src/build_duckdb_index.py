"""Build a native DuckDB blocking index for the full-scale dataset."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import duckdb

from entity_resolution.normalize import normalize_blocking_fields


def normalized_expression(column: str, replacements: tuple[tuple[str, str], ...]) -> str:
    expression = f"lower(coalesce({column}, ''))"
    expression = f"regexp_replace({expression}, '&', ' and ', 'g')"
    expression = f"regexp_replace({expression}, '[^[:alnum:]]+', ' ', 'g')"
    expression = f"trim(regexp_replace({expression}, ' +', ' ', 'g'))"
    for old, new in replacements:
        expression = f"regexp_replace({expression}, '\\\\b{old}\\\\b', '{new}', 'g')"
    return expression


def build(
    con: duckdb.DuckDBPyConnection,
    dataset: Path,
    split: str,
    cap: int,
    max_rows: int | None,
    chunk_rows: int,
) -> int:
    con.execute("DROP TABLE IF EXISTS target_records")
    con.execute("DROP TABLE IF EXISTS keys")
    con.execute(
        """CREATE TABLE target_records(
            entity_id VARCHAR, source VARCHAR, country VARCHAR, name VARCHAR, address VARCHAR
        )"""
    )
    con.execute(
        """CREATE TABLE keys(
            country VARCHAR, key_type VARCHAR, key_value VARCHAR, entity_id VARCHAR
        )"""
    )
    con.execute(
        """CREATE TEMP TABLE batch_records(
            entity_id VARCHAR, source VARCHAR, country VARCHAR, name VARCHAR, address VARCHAR
        )"""
    )
    key_select = """
        SELECT country, 'name_exact' AS key_type, name AS key_value, entity_id
        FROM batch_records WHERE name <> ''
        UNION ALL
        SELECT country, 'address_exact', address, entity_id
        FROM batch_records WHERE address <> ''
        UNION ALL
        SELECT r.country, 'name_token', token, r.entity_id
        FROM batch_records r, UNNEST(string_split(r.name, ' ')) AS t(token)
        WHERE length(token) >= 4
        UNION ALL
        SELECT r.country, 'address_token', token, r.entity_id
        FROM batch_records r, UNNEST(string_split(r.address, ' ')) AS t(token)
        WHERE length(token) >= 4
    """
    records_count = 0
    for number in (2, 3):
        source_path = (dataset / split / f"{split}_source{number}.tsv").as_posix()
        source_rows = 0
        with Path(source_path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            while max_rows is None or source_rows < max_rows:
                rows = []
                for _ in range(chunk_rows):
                    if max_rows is not None and source_rows + len(rows) >= max_rows:
                        break
                    try:
                        row = next(reader)
                    except StopIteration:
                        break
                    country, name, name_tokens, address_tokens, address = (
                        normalize_blocking_fields(
                            row["business_name"], row["business_address"], row["country"]
                        )
                    )
                    rows.append((row["entity_id"], f"S{number}", country, name, address))
                if not rows:
                    break
                con.execute("DELETE FROM batch_records")
                con.executemany("INSERT INTO batch_records VALUES (?, ?, ?, ?, ?)", rows)
                con.execute("INSERT INTO target_records SELECT * FROM batch_records")
                con.execute("INSERT INTO keys " + key_select)
                source_rows += len(rows)
                records_count += len(rows)
                if len(rows) < chunk_rows:
                    break
    con.execute(
        """CREATE OR REPLACE TABLE allowed_tokens AS
        SELECT country, key_type, key_value
        FROM keys
        WHERE key_type IN ('name_token', 'address_token')
        GROUP BY ALL
        HAVING count(*) <= ?""",
        [cap],
    )
    con.execute(
        """CREATE OR REPLACE TABLE filtered_keys AS
        SELECT k.*
        FROM keys k
        LEFT JOIN allowed_tokens a USING (country, key_type, key_value)
        WHERE k.key_type NOT IN ('name_token', 'address_token')
           OR a.key_value IS NOT NULL"""
    )
    con.execute("DROP TABLE keys")
    con.execute("ALTER TABLE filtered_keys RENAME TO keys")
    con.execute("DROP TABLE allowed_tokens")
    return records_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--split", choices=("train", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-token-frequency", type=int, default=250)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--chunk-rows", type=int, default=50000)
    parser.add_argument("--memory-limit", default="4GB")
    parser.add_argument("--temp-directory", type=Path, default=Path("work/duckdb_tmp"))
    args = parser.parse_args()

    if args.output.exists():
        args.output.unlink()
    args.temp_directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    con = duckdb.connect(str(args.output))
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"PRAGMA temp_directory='{args.temp_directory.resolve().as_posix()}'")
    con.execute("PRAGMA threads=2")
    records = build(
        con, args.dataset, args.split, args.max_token_frequency, args.max_rows,
        args.chunk_rows,
    )
    keys = con.execute("SELECT count(*) FROM keys").fetchone()[0]
    con.close()
    print(json.dumps({
        "database": str(args.output),
        "records": records,
        "keys": keys,
        "seconds": round(time.perf_counter() - started, 3),
    }, indent=2))


if __name__ == "__main__":
    main()
