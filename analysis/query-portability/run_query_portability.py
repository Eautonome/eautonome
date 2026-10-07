#!/usr/bin/env python3
"""Cross-dataset portability of the 13 released Eautonome SPARQL queries.

Builds no methodology prose. Writes CSV/JSON under results/ only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Graph

ROOT = Path(__file__).resolve().parents[2]
QUERIES_DIR = ROOT / "queries"
EXPECTED_CSV = ROOT / "expected-results.csv"
ONTOLOGY = ROOT / "docs" / "ontology" / "eautonome.ttl"
NATIVE_HYDRO = ROOT / "docs" / "data" / "hydrodynamic-observations.jsonld"
NATIVE_SHOWER = ROOT / "docs" / "data" / "shower-observations.jsonld"
HSB_RESULTS = ROOT / "analysis" / "external-hsb" / "external-reuse-query-results.csv"
WEUSEDTO_MAPPER = ROOT / "analysis" / "external-weusedto" / "run_weusedto_external_reuse.py"

DATASETS = ("EAUTONOME", "HSB", "WEUSEDTO")
STATUSES = {
    "SUPPORTED_UNCHANGED",
    "SUPPORTED_WITH_PARAMETERIZATION",
    "PARTIAL",
    "NOT_ANSWERABLE_FROM_SOURCE",
}
QUERY_IDS = [f"Q{i}" for i in range(1, 14)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_query(qid: str) -> str:
    n = int(qid[1:])
    return (QUERIES_DIR / f"q{n:02d}.rq").read_text(encoding="utf-8")


def load_expected() -> Dict[str, int]:
    out: Dict[str, int] = {}
    with EXPECTED_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["query"]] = int(row["expected_rows"])
    return out


def load_weusedto_mapper():
    name = "weusedto_external_reuse"
    spec = importlib.util.spec_from_file_location(name, WEUSEDTO_MAPPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load mapper: {WEUSEDTO_MAPPER}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # required before exec for @dataclass on Py3.14
    spec.loader.exec_module(mod)
    return mod


def build_native_graph() -> Graph:
    g = Graph()
    g.parse(ONTOLOGY, format="turtle")
    g.parse(NATIVE_HYDRO, format="json-ld")
    g.parse(NATIVE_SHOWER, format="json-ld")
    return g


def run_queries(g: Graph) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for qid in QUERY_IDS:
        counts[qid] = len(list(g.query(load_query(qid))))
    return counts


def build_weusedto_full_graph(data_dir: Path, mapper) -> Graph:
    """In-memory full mapped graph. Never serialize this graph."""
    series_paths, _, _ = mapper.resolve_series_files(data_dir)
    full = Graph()
    mapper.add_common_prefixes(full)
    mapper.add_dataset_provenance(full)
    # example_limit=0: only full_graph receives observation/event triples
    example = Graph()
    mapper.add_common_prefixes(example)
    for series in sorted(series_paths.keys(), key=lambda s: (mapper.DOCUMENTED_SERIES[s]["format"], s)):
        path = series_paths[series]
        fmt = mapper.DOCUMENTED_SERIES[series]["format"]
        if fmt == "A":
            mapper.process_format_a(series, path, full, example, 0)
        else:
            mapper.process_format_b(series, path, full, example, 0)
    return full


def classify_eautonome(counts: Dict[str, int], expected: Dict[str, int]) -> List[dict]:
    rows = []
    for qid in QUERY_IDS:
        if counts[qid] != expected[qid]:
            raise RuntimeError(
                f"native {qid}: got {counts[qid]} rows, expected {expected[qid]}"
            )
        rows.append({
            "query_id": qid,
            "dataset": "EAUTONOME",
            "status": "SUPPORTED_UNCHANGED",
            "row_count": counts[qid],
            "execution_mode": "ORIGINAL",
            "reason_code": "NATIVE_BASELINE",
            "reason": "Released query matches expected-results.csv on native instance data.",
        })
    return rows


def classify_hsb() -> List[dict]:
    """Use committed HSB query evidence only. Do not remap HSB."""
    by_query: Dict[str, dict] = {}
    with HSB_RESULTS.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            by_query[row["query"]] = row

    # Fixed classifications from committed HSB evaluation artefacts.
    # Q10 uses analysis/external-hsb/queries/q10-hsb.rq (deployment IRI only).
    plan = {
        "Q1": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "HSB observations link sensors; original query answered."),
        "Q2": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "HSB observations assert observedProperty FlowVolume."),
        "Q3": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "HSB supplies room and fixture asset links for measurement points."),
        "Q4": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "HSB observations assert hasSimpleResult."),
        "Q5": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "HSB observations assert resultTime from source timestamps."),
        "Q6": ("NOT_ANSWERABLE_FROM_SOURCE", "NOT_EXECUTED", "SOURCE_METADATA_ABSENT",
               "HSB source has no operational status."),
        "Q7": ("NOT_ANSWERABLE_FROM_SOURCE", "NOT_EXECUTED", "SOURCE_METADATA_ABSENT",
               "HSB source has no consumption event intervals."),
        "Q8": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "HSB observations assert usedProcedure."),
        "Q9": ("NOT_ANSWERABLE_FROM_SOURCE", "NOT_EXECUTED", "SOURCE_METADATA_ABSENT",
               "HSB source has no calibration parameters."),
        "Q10": ("SUPPORTED_WITH_PARAMETERIZATION", "PARAMETERIZED", "DATASET_SPECIFIC_IRI",
                "Same query with eau:hsbDeployment substituted for eau:eautonomeDeployment."),
        "Q11": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
                "HSB measurement points assert eau:locatedIn."),
        "Q12": ("NOT_ANSWERABLE_FROM_SOURCE", "NOT_EXECUTED", "SOURCE_METADATA_ABSENT",
                "HSB source has no operational status for inactive/planned filter."),
        "Q13": ("NOT_ANSWERABLE_FROM_SOURCE", "NOT_EXECUTED", "SOURCE_METADATA_ABSENT",
                "HSB source has no observation collections or consumption events."),
    }

    rows = []
    for qid in QUERY_IDS:
        status, mode, code, reason = plan[qid]
        if qid == "Q10":
            evidence = by_query.get("Q10-HSB")
            if evidence is None:
                raise RuntimeError("HSB evidence missing Q10-HSB row")
            row_count: Optional[int] = int(evidence["row_count"]) if evidence["row_count"] else None
        else:
            evidence = by_query.get(qid)
            if evidence is None:
                raise RuntimeError(f"HSB evidence missing {qid}")
            raw = evidence.get("row_count", "")
            row_count = int(raw) if raw not in ("", None) else None
        rows.append({
            "query_id": qid,
            "dataset": "HSB",
            "status": status,
            "row_count": row_count if row_count is not None else "",
            "execution_mode": mode,
            "reason_code": code,
            "reason": reason,
        })
    return rows


def classify_weusedto(counts: Dict[str, int]) -> List[dict]:
    """Classify from executed counts plus known WEUSEDTO mapping limits."""
    # Format A resultTime uses an instantaneous-sample assumption (mapper note).
    # Format B alone supplies ConsumptionEvent / ObservationCollection structure.
    plan = {
        "Q1": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "Mapped observations assert madeBySensor for all processed series."),
        "Q2": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "Mapped observations assert observedProperty s4watr:FlowRate."),
        "Q3": ("NOT_ANSWERABLE_FROM_SOURCE", "ORIGINAL", "SOURCE_METADATA_ABSENT",
               "WEUSEDTO has no room or fixture asset; locatedIn/measuresOnAsset not mapped."),
        "Q4": ("SUPPORTED_UNCHANGED", "ORIGINAL", "SOURCE_METADATA_PRESENT",
               "Mapped observations assert hasSimpleResult from source flow values."),
        "Q5": ("PARTIAL", "ORIGINAL", "MODELLING_ASSUMPTION",
               "Format A sample epoch stored as resultTime; Format B has no resultTime."),
        "Q6": ("NOT_ANSWERABLE_FROM_SOURCE", "ORIGINAL", "SOURCE_METADATA_ABSENT",
               "WEUSEDTO source has no operational status."),
        "Q7": ("PARTIAL", "ORIGINAL", "PARTIAL_SOURCE_COVERAGE",
               "Native Format B intervals map to collections/events; Format A has none."),
        "Q8": ("NOT_ANSWERABLE_FROM_SOURCE", "ORIGINAL", "SOURCE_METADATA_ABSENT",
               "WEUSEDTO mapping does not assert usedProcedure."),
        "Q9": ("NOT_ANSWERABLE_FROM_SOURCE", "ORIGINAL", "SOURCE_METADATA_ABSENT",
               "WEUSEDTO source has no calibration parameters."),
        "Q10": ("PARTIAL", "ORIGINAL", "PARTIAL_MAPPING",
                "Source describes a residential monitoring setup, but the mapping does not materialize a deployment or deployedSystem links."),
        "Q11": ("NOT_ANSWERABLE_FROM_SOURCE", "ORIGINAL", "SOURCE_METADATA_ABSENT",
                "WEUSEDTO has no room metadata; eau:locatedIn not mapped."),
        "Q12": ("NOT_ANSWERABLE_FROM_SOURCE", "ORIGINAL", "SOURCE_METADATA_ABSENT",
                "WEUSEDTO source has no operational status."),
        "Q13": ("PARTIAL", "ORIGINAL", "PARTIAL_SOURCE_COVERAGE",
                "Format B supplies collection/event/member links; Format A has none."),
    }
    rows = []
    for qid in QUERY_IDS:
        status, mode, code, reason = plan[qid]
        rows.append({
            "query_id": qid,
            "dataset": "WEUSEDTO",
            "status": status,
            "row_count": counts[qid],
            "execution_mode": mode,
            "reason_code": code,
            "reason": reason,
        })
    return rows


def write_long_csv(path: Path, rows: List[dict]) -> None:
    fields = [
        "query_id", "dataset", "status", "row_count",
        "execution_mode", "reason_code", "reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_matrix_csv(path: Path, rows: List[dict]) -> None:
    by_qd = {(r["query_id"], r["dataset"]): r for r in rows}
    fields = [
        "query_id",
        "eautonome_status", "eautonome_rows",
        "hsb_status", "hsb_rows",
        "weusedto_status", "weusedto_rows",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for qid in QUERY_IDS:
            e = by_qd[(qid, "EAUTONOME")]
            h = by_qd[(qid, "HSB")]
            w_ = by_qd[(qid, "WEUSEDTO")]
            w.writerow({
                "query_id": qid,
                "eautonome_status": e["status"],
                "eautonome_rows": e["row_count"],
                "hsb_status": h["status"],
                "hsb_rows": h["row_count"],
                "weusedto_status": w_["status"],
                "weusedto_rows": w_["row_count"],
            })


def status_counts(rows: List[dict], dataset: str) -> Dict[str, int]:
    c = Counter(r["status"] for r in rows if r["dataset"] == dataset)
    return {s: c.get(s, 0) for s in sorted(STATUSES)}


def validate(
    rows: List[dict],
    hashes_before: Dict[str, str],
    hashes_after: Dict[str, str],
    full_graph_paths: List[Path],
) -> List[str]:
    errors: List[str] = []
    if len(rows) != 39:
        errors.append(f"expected 39 long rows, got {len(rows)}")
    seen = {(r["query_id"], r["dataset"]) for r in rows}
    for qid in QUERY_IDS:
        for ds in DATASETS:
            if (qid, ds) not in seen:
                errors.append(f"missing combination {qid}/{ds}")
    for r in rows:
        if r["status"] not in STATUSES:
            errors.append(f"illegal status {r['status']} on {r['query_id']}/{r['dataset']}")
    for key, before in hashes_before.items():
        if hashes_after.get(key) != before:
            errors.append(f"input changed during run: {key}")
    for p in full_graph_paths:
        if p.exists():
            errors.append(f"WEUSEDTO full graph must not be serialized: {p}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "weusedto_data_dir",
        type=Path,
        help="External WEUSEDTO data/ directory (CSVs not in this repo)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        help="Directory for CSV/JSON artefacts",
    )
    args = parser.parse_args()

    if not args.weusedto_data_dir.is_dir():
        raise SystemExit(f"WEUSEDTO data dir not found: {args.weusedto_data_dir}")
    if not HSB_RESULTS.is_file():
        raise SystemExit(f"HSB evidence missing: {HSB_RESULTS}")

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    # Forbidden full-graph dump paths under this evaluation
    forbidden_full = [
        out / "weusedto-full.ttl",
        out / "weusedto-full.jsonld",
        out / "weusedto-full.nt",
        out / "weusedto-full-graph.ttl",
    ]

    hashes_before = {
        "docs/ontology/eautonome.ttl": sha256_file(ONTOLOGY),
        "expected-results.csv": sha256_file(EXPECTED_CSV),
        "analysis/external-hsb/external-reuse-query-results.csv": sha256_file(HSB_RESULTS),
        "analysis/external-weusedto/run_weusedto_external_reuse.py": sha256_file(WEUSEDTO_MAPPER),
    }
    for i in range(1, 14):
        rel = f"queries/q{i:02d}.rq"
        hashes_before[rel] = sha256_file(ROOT / rel)

    expected = load_expected()

    print("Building native graph...", flush=True)
    native_g = build_native_graph()
    print("Running native queries...", flush=True)
    native_counts = run_queries(native_g)
    eau_rows = classify_eautonome(native_counts, expected)
    hsb_rows = classify_hsb()

    print("Loading WEUSEDTO mapper...", flush=True)
    mapper = load_weusedto_mapper()
    series_paths, _, _ = mapper.resolve_series_files(args.weusedto_data_dir)
    weusedto_source_hashes = {
        path.name: sha256_file(path) for path in sorted(series_paths.values(), key=lambda p: p.name)
    }
    print("Building WEUSEDTO full graph in memory...", flush=True)
    weu_g = build_weusedto_full_graph(args.weusedto_data_dir, mapper)
    print(f"WEUSEDTO triples: {len(weu_g)}", flush=True)
    print("Running WEUSEDTO queries...", flush=True)
    weu_counts = run_queries(weu_g)
    # Drop full graph before writing artefacts
    del weu_g
    weu_rows = classify_weusedto(weu_counts)

    rows = eau_rows + hsb_rows + weu_rows
    # Stable order: query then dataset
    order = {ds: i for i, ds in enumerate(DATASETS)}
    rows.sort(key=lambda r: (int(r["query_id"][1:]), order[r["dataset"]]))

    hashes_after = {
        "docs/ontology/eautonome.ttl": sha256_file(ONTOLOGY),
        "expected-results.csv": sha256_file(EXPECTED_CSV),
        "analysis/external-hsb/external-reuse-query-results.csv": sha256_file(HSB_RESULTS),
        "analysis/external-weusedto/run_weusedto_external_reuse.py": sha256_file(WEUSEDTO_MAPPER),
    }
    for i in range(1, 14):
        rel = f"queries/q{i:02d}.rq"
        hashes_after[rel] = sha256_file(ROOT / rel)

    errors = validate(rows, hashes_before, hashes_after, forbidden_full)

    long_path = out / "portability-long.csv"
    matrix_path = out / "portability-matrix.csv"
    summary_path = out / "portability-summary.json"

    write_long_csv(long_path, rows)
    write_matrix_csv(matrix_path, rows)

    # Re-read matrix row count
    with matrix_path.open(newline="", encoding="utf-8") as fh:
        matrix_n = sum(1 for _ in csv.DictReader(fh))
    if matrix_n != 13:
        errors.append(f"expected 13 matrix rows, got {matrix_n}")

    q10_weu = next(r for r in rows if r["query_id"] == "Q10" and r["dataset"] == "WEUSEDTO")
    if q10_weu["status"] != "PARTIAL" or q10_weu["row_count"] != 0:
        errors.append(
            f"WEUSEDTO Q10 must be PARTIAL with 0 rows; got {q10_weu['status']} / {q10_weu['row_count']}"
        )

    summary: Dict[str, Any] = {
        "queries": 13,
        "datasets": list(DATASETS),
        "expected_combinations": 39,
        "actual_combinations": len(rows),
        "status_counts": {
            "EAUTONOME": status_counts(rows, "EAUTONOME"),
            "HSB": status_counts(rows, "HSB"),
            "WEUSEDTO": status_counts(rows, "WEUSEDTO"),
        },
        "native_expected_counts_match": all(
            native_counts[q] == expected[q] for q in QUERY_IDS
        ),
        "ontology_schema_changed": (
            hashes_before["docs/ontology/eautonome.ttl"]
            != hashes_after["docs/ontology/eautonome.ttl"]
        ),
        "released_queries_changed": any(
            hashes_before[f"queries/q{i:02d}.rq"] != hashes_after[f"queries/q{i:02d}.rq"]
            for i in range(1, 14)
        ),
        "weusedto_full_graph_serialized": False,
        "input_sha256": {
            k: v for k, v in hashes_before.items()
            if k.startswith("docs/") or k.startswith("queries/") or k == "expected-results.csv"
        },
        "external_input_sha256": {
            "hsb_query_evidence": hashes_before[
                "analysis/external-hsb/external-reuse-query-results.csv"
            ],
            "weusedto_mapper": hashes_before[
                "analysis/external-weusedto/run_weusedto_external_reuse.py"
            ],
            "weusedto_source_files": weusedto_source_hashes,
        },
        "weusedto_query_row_counts": weu_counts,
        "validation_errors": errors,
        "validation_passed": len(errors) == 0,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "validation_passed": summary["validation_passed"],
        "validation_errors": errors,
        "status_counts": summary["status_counts"],
        "files": [str(long_path), str(matrix_path), str(summary_path)],
    }, indent=2))
    return 0 if summary["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
