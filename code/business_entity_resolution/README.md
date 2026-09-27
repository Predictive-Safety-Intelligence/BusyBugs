# BusyBugs Business Entity Resolution

This package implements the challenge pipeline using only the supplied data:
canonical local normalization, country-aware exact/token blocking in DuckDB,
pair scoring, and incremental TSV output.

## Reproduce

From the submission root:

```cmd
python -m pip install -r code\business_entity_resolution\requirements.txt
python code\build_duckdb_index.py --split test --chunk-rows 10000 --max-token-frequency 100 --memory-limit 2GB --output work\targets_duck_test.duckdb
python code\business_entity_resolution\src\run_pipeline.py --dataset dataset --index work\targets_duck_test.duckdb --output output
python utils\validate_submission.py --matching output\matching_results.tsv --candidate output\candidate_pairs.tsv --test-dir dataset\test
```

For a quick, complete last-mile run on Windows (no prebuilt index required),
use the DuckDB exact-join path:

```cmd
python code\business_entity_resolution\src\run_exact_submission.py --dataset dataset --output output
```

It writes one row for every test Source-1 entity. Matches are selected from
exact normalized name/address joins (exact name+address first, then unique
exact-name/address fallbacks), and candidates always contain the selected IDs.
Use `--max-source1 10000` for a bounded smoke test before the full run.

The index builder is kept in the parent `code/` directory for the working
submission; copy it into `src/` when packaging a completely standalone archive.
`--chunk-rows` controls memory usage. `--max-token-frequency` removes generic
tokens while retaining exact keys.

## Structure

- `src/entity_resolution/normalize.py`: deterministic normalization.
- `src/entity_resolution/features.py`: RapidFuzz and overlap features.
- `src/run_pipeline.py`: batch inference and required TSV writers.
- `requirements.txt`: pinned major dependency ranges.
