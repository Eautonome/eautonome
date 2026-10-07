#!/usr/bin/env python3
"""Derive query information requirements and explain committed portability statuses."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
QUERIES_DIR = ROOT / "queries"
ONTOLOGY = ROOT / "docs" / "ontology" / "eautonome.ttl"
PORTABILITY_LONG = ROOT / "analysis" / "query-portability" / "results" / "portability-long.csv"

DATASETS = ("EAUTONOME", "HSB", "WEUSEDTO")
QUERY_IDS = [f"Q{i}" for i in range(1, 14)]
STATES = {"AVAILABLE", "PARTIAL", "MISSING", "DATASET_SPECIFIC"}
AGG_ORDER = (
    ("MISSING", "NOT_ANSWERABLE_FROM_SOURCE"),
    ("PARTIAL", "PARTIAL"),
    ("DATASET_SPECIFIC", "SUPPORTED_WITH_PARAMETERIZATION"),
)

# (requirement_id, requirement_kind, rdf_terms, fragments that must appear in the query text)
ReqDef = Tuple[str, str, str, Tuple[str, ...]]

# Atomic requirements taken from released SPARQL patterns/filters only.
QUERY_REQUIREMENTS: Dict[str, List[ReqDef]] = {
    "Q1": [
        ("OBSERVATION_TYPE", "CLASS", "sosa:Observation", ("sosa:Observation",)),
        ("OBSERVATION_SENSOR_LINK", "PROPERTY", "sosa:madeBySensor", ("sosa:madeBySensor",)),
    ],
    "Q2": [
        ("OBSERVATION_TYPE", "CLASS", "sosa:Observation", ("sosa:Observation",)),
        ("OBSERVED_PROPERTY", "PROPERTY", "sosa:observedProperty", ("sosa:observedProperty",)),
    ],
    "Q3": [
        ("MEASUREMENT_POINT_TYPE", "CLASS", "eau:MeasurementPoint", ("eau:MeasurementPoint",)),
        ("MEASUREMENT_POINT_ROOM_LINK", "PROPERTY", "eau:locatedIn", ("eau:locatedIn",)),
        ("MEASUREMENT_POINT_ASSET_LINK", "PROPERTY", "eau:measuresOnAsset", ("eau:measuresOnAsset",)),
    ],
    "Q4": [
        ("OBSERVATION_TYPE", "CLASS", "sosa:Observation", ("sosa:Observation",)),
        ("SIMPLE_RESULT", "PROPERTY", "sosa:hasSimpleResult", ("sosa:hasSimpleResult",)),
    ],
    "Q5": [
        ("OBSERVATION_TYPE", "CLASS", "sosa:Observation", ("sosa:Observation",)),
        ("RESULT_TIME", "PROPERTY", "sosa:resultTime", ("sosa:resultTime",)),
    ],
    "Q6": [
        ("OPERATIONAL_STATUS", "PROPERTY", "eau:hasOperationalStatus", ("eau:hasOperationalStatus",)),
    ],
    "Q7": [
        ("OBSERVATION_COLLECTION_TYPE", "CLASS", "sosa:ObservationCollection", ("sosa:ObservationCollection",)),
        ("PHENOMENON_TIME", "PROPERTY", "sosa:phenomenonTime", ("sosa:phenomenonTime",)),
        ("INTERVAL_BEGIN", "PROPERTY_PATH", "time:hasBeginning/time:inXSDDateTime",
         ("time:hasBeginning", "time:inXSDDateTime")),
        ("INTERVAL_END", "PROPERTY_PATH", "time:hasEnd/time:inXSDDateTime",
         ("time:hasEnd", "time:inXSDDateTime")),
        ("CONSUMPTION_EVENT_LINK", "PROPERTY", "eau:hasConsumptionEvent", ("eau:hasConsumptionEvent",)),
    ],
    "Q8": [
        ("OBSERVATION_TYPE", "CLASS", "sosa:Observation", ("sosa:Observation",)),
        ("USED_PROCEDURE", "PROPERTY", "sosa:usedProcedure", ("sosa:usedProcedure",)),
    ],
    "Q9": [
        ("SENSOR_TYPE_ASSERTION", "PROPERTY", "rdf:type", (" a ",)),
        ("SENSOR_TYPE_HIERARCHY", "PROPERTY_PATH", "rdfs:subClassOf* → sosa:Sensor",
         ("rdfs:subClassOf*", "sosa:Sensor")),
        ("CALIBRATION_SLOPE", "PROPERTY", "eau:hasCalibrationSlope", ("eau:hasCalibrationSlope",)),
        ("CALIBRATION_R2", "PROPERTY", "eau:hasCalibrationR2", ("eau:hasCalibrationR2",)),
    ],
    "Q10": [
        ("DEPLOYMENT_IDENTIFIER", "IDENTIFIER", "eau:eautonomeDeployment", ("eau:eautonomeDeployment",)),
        ("DEPLOYED_SYSTEM_LINK", "PROPERTY", "sosa:deployedSystem", ("sosa:deployedSystem",)),
        ("SENSOR_TYPE_ASSERTION", "PROPERTY", "rdf:type", (" a ",)),
        ("SENSOR_TYPE_HIERARCHY", "PROPERTY_PATH", "rdfs:subClassOf* → sosa:Sensor",
         ("rdfs:subClassOf*", "sosa:Sensor")),
    ],
    "Q11": [
        ("OBSERVATION_TYPE", "CLASS", "sosa:Observation", ("sosa:Observation",)),
        ("OBSERVATION_FEATURE_OF_INTEREST", "PROPERTY", "sosa:hasFeatureOfInterest",
         ("sosa:hasFeatureOfInterest",)),
        ("MEASUREMENT_POINT_ROOM_LINK", "PROPERTY", "eau:locatedIn", ("eau:locatedIn",)),
    ],
    "Q12": [
        ("SENSOR_MONITORS_MEASUREMENT_POINT", "PROPERTY", "eau:monitors", ("eau:monitors",)),
        ("OPERATIONAL_STATUS", "PROPERTY", "eau:hasOperationalStatus", ("eau:hasOperationalStatus",)),
        ("STATUS_FILTER_VALUES", "FILTER_VALUE", '"inactive"|"planned"',
         ('"inactive"', '"planned"')),
    ],
    "Q13": [
        ("OBSERVATION_COLLECTION_TYPE", "CLASS", "sosa:ObservationCollection", ("sosa:ObservationCollection",)),
        ("CONSUMPTION_EVENT_LINK", "PROPERTY", "eau:hasConsumptionEvent", ("eau:hasConsumptionEvent",)),
        ("COLLECTION_MEMBER", "PROPERTY", "sosa:hasMember", ("sosa:hasMember",)),
    ],
}

# Coverage for each unique requirement_id × dataset: (state, evidence_code)
COVERAGE: Dict[str, Dict[str, Tuple[str, str]]] = {
    "OBSERVATION_TYPE": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("AVAILABLE", "MAPPED_DIRECTLY"),
    },
    "OBSERVATION_SENSOR_LINK": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("AVAILABLE", "MAPPED_DIRECTLY"),
    },
    "OBSERVED_PROPERTY": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("AVAILABLE", "MAPPED_DIRECTLY"),
    },
    "MEASUREMENT_POINT_TYPE": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("PARTIAL", "PARTIAL_MEASUREMENT_POINT_MAPPING"),
    },
    "MEASUREMENT_POINT_ROOM_LINK": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("MISSING", "SOURCE_METADATA_ABSENT"),
    },
    "MEASUREMENT_POINT_ASSET_LINK": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("MISSING", "SOURCE_METADATA_ABSENT"),
    },
    "SIMPLE_RESULT": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("AVAILABLE", "MAPPED_DIRECTLY"),
    },
    "RESULT_TIME": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("PARTIAL", "MODELLING_ASSUMPTION"),
    },
    "OPERATIONAL_STATUS": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("MISSING", "SOURCE_METADATA_ABSENT"),
    },
    "STATUS_FILTER_VALUES": {
        "EAUTONOME": ("AVAILABLE", "QUERY_CONSTANT"),
        "HSB": ("AVAILABLE", "QUERY_CONSTANT"),
        "WEUSEDTO": ("AVAILABLE", "QUERY_CONSTANT"),
    },
    "SENSOR_TYPE_ASSERTION": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("AVAILABLE", "MAPPED_DIRECTLY"),
    },
    "OBSERVATION_COLLECTION_TYPE": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("PARTIAL", "FORMAT_B_ONLY"),
    },
    "PHENOMENON_TIME": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("PARTIAL", "FORMAT_B_ONLY"),
    },
    "INTERVAL_BEGIN": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("PARTIAL", "FORMAT_B_ONLY"),
    },
    "INTERVAL_END": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("PARTIAL", "FORMAT_B_ONLY"),
    },
    "CONSUMPTION_EVENT_LINK": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("PARTIAL", "FORMAT_B_ONLY"),
    },
    "COLLECTION_MEMBER": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("PARTIAL", "FORMAT_B_ONLY"),
    },
    "USED_PROCEDURE": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("MISSING", "SOURCE_METADATA_ABSENT"),
    },
    "SENSOR_TYPE_HIERARCHY": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("AVAILABLE", "MAPPED_DIRECTLY"),
    },
    "CALIBRATION_SLOPE": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("MISSING", "SOURCE_METADATA_ABSENT"),
    },
    "CALIBRATION_R2": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("MISSING", "SOURCE_METADATA_ABSENT"),
        "WEUSEDTO": ("MISSING", "SOURCE_METADATA_ABSENT"),
    },
    "DEPLOYMENT_IDENTIFIER": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("DATASET_SPECIFIC", "DATASET_SPECIFIC_IRI"),
        "WEUSEDTO": ("PARTIAL", "PARTIAL_MAPPING"),
    },
    "DEPLOYED_SYSTEM_LINK": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("PARTIAL", "PARTIAL_MAPPING"),
    },
    "OBSERVATION_FEATURE_OF_INTEREST": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("PARTIAL", "PARTIAL_MEASUREMENT_POINT_MAPPING"),
    },
    "SENSOR_MONITORS_MEASUREMENT_POINT": {
        "EAUTONOME": ("AVAILABLE", "NATIVE_DATA"),
        "HSB": ("AVAILABLE", "MAPPED_DIRECTLY"),
        "WEUSEDTO": ("PARTIAL", "PARTIAL_MEASUREMENT_POINT_MAPPING"),
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_query_text(qid: str) -> str:
    n = int(qid[1:])
    return (QUERIES_DIR / f"q{n:02d}.rq").read_text(encoding="utf-8")


def derive_status(states: Sequence[str]) -> str:
    for needle, status in AGG_ORDER:
        if needle in states:
            return status
    return "SUPPORTED_UNCHANGED"


def load_committed_statuses() -> Dict[Tuple[str, str], str]:
    out: Dict[Tuple[str, str], str] = {}
    with PORTABILITY_LONG.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["query_id"], row["dataset"])] = row["status"]
    return out


def main() -> int:
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    hashes_before = {
        "docs/ontology/eautonome.ttl": sha256_file(ONTOLOGY),
        "analysis/query-portability/results/portability-long.csv": sha256_file(PORTABILITY_LONG),
    }
    for i in range(1, 14):
        rel = f"queries/q{i:02d}.rq"
        hashes_before[rel] = sha256_file(ROOT / rel)

    errors: List[str] = []
    req_rows: List[dict] = []
    unique_ids = set()

    for qid in QUERY_IDS:
        if qid not in QUERY_REQUIREMENTS:
            errors.append(f"missing requirement list for {qid}")
            continue
        text = load_query_text(qid)
        for req_id, kind, rdf_terms, fragments in QUERY_REQUIREMENTS[qid]:
            unique_ids.add(req_id)
            for frag in fragments:
                if frag not in text:
                    errors.append(f"{qid}/{req_id}: fragment {frag!r} not in released query")
            if req_id not in COVERAGE:
                errors.append(f"no coverage defined for {req_id}")
            req_rows.append({
                "query_id": qid,
                "requirement_id": req_id,
                "requirement_kind": kind,
                "rdf_terms": rdf_terms,
            })

    coverage_rows: List[dict] = []
    for req_id in sorted(unique_ids):
        for ds in DATASETS:
            if req_id not in COVERAGE or ds not in COVERAGE[req_id]:
                errors.append(f"missing coverage {req_id}/{ds}")
                continue
            state, evidence = COVERAGE[req_id][ds]
            if state not in STATES:
                errors.append(f"illegal state {state} for {req_id}/{ds}")
            coverage_rows.append({
                "requirement_id": req_id,
                "dataset": ds,
                "state": state,
                "evidence_code": evidence,
            })

    committed = load_committed_statuses()
    if len(committed) != 39:
        errors.append(f"committed portability-long has {len(committed)} rows, expected 39")

    mismatches: List[dict] = []
    derived: Dict[Tuple[str, str], str] = {}
    for qid in QUERY_IDS:
        req_ids = [r[0] for r in QUERY_REQUIREMENTS[qid]]
        for ds in DATASETS:
            states = [COVERAGE[rid][ds][0] for rid in req_ids]
            status = derive_status(states)
            derived[(qid, ds)] = status
            expected = committed.get((qid, ds))
            if expected != status:
                mismatches.append({
                    "query_id": qid,
                    "dataset": ds,
                    "derived": status,
                    "committed": expected,
                })

    if mismatches:
        errors.append(f"{len(mismatches)} derived/committed status mismatch(es)")

    # blocking = MISSING requirements → affected queries (external datasets only)
    blocking: Dict[str, Dict[str, List[str]]] = {"HSB": {}, "WEUSEDTO": {}}
    for ds in ("HSB", "WEUSEDTO"):
        miss_to_queries: Dict[str, List[str]] = defaultdict(list)
        for qid in QUERY_IDS:
            for req_id, *_ in QUERY_REQUIREMENTS[qid]:
                if COVERAGE[req_id][ds][0] == "MISSING":
                    if qid not in miss_to_queries[req_id]:
                        miss_to_queries[req_id].append(qid)
        blocking[ds] = {k: sorted(v, key=lambda x: int(x[1:])) for k, v in sorted(miss_to_queries.items())}

    state_counts: Dict[str, Dict[str, int]] = {}
    for ds in DATASETS:
        c = defaultdict(int)
        for row in coverage_rows:
            if row["dataset"] == ds:
                c[row["state"]] += 1
        state_counts[ds] = {s: c.get(s, 0) for s in sorted(STATES)}

    hashes_after = {
        "docs/ontology/eautonome.ttl": sha256_file(ONTOLOGY),
        "analysis/query-portability/results/portability-long.csv": sha256_file(PORTABILITY_LONG),
    }
    for i in range(1, 14):
        rel = f"queries/q{i:02d}.rq"
        hashes_after[rel] = sha256_file(ROOT / rel)
    for key, before in hashes_before.items():
        if hashes_after.get(key) != before:
            errors.append(f"input changed during run: {key}")

    req_csv = out_dir / "query-requirements.csv"
    cov_csv = out_dir / "requirement-coverage.csv"
    summary_json = out_dir / "requirement-summary.json"

    with req_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["query_id", "requirement_id", "requirement_kind", "rdf_terms"],
        )
        w.writeheader()
        w.writerows(req_rows)

    with cov_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["requirement_id", "dataset", "state", "evidence_code"],
        )
        w.writeheader()
        w.writerows(coverage_rows)

    summary = {
        "queries": 13,
        "datasets": list(DATASETS),
        "unique_requirements": len(unique_ids),
        "query_requirement_rows": len(req_rows),
        "requirement_coverage_rows": len(coverage_rows),
        "derived_portability_matches_committed": len(mismatches) == 0,
        "status_mismatches": mismatches,
        "requirement_state_counts": state_counts,
        "blocking_requirements": blocking,
        "input_sha256": hashes_before,
        "validation_errors": errors,
        "validation_passed": len(errors) == 0,
    }
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "unique_requirements": summary["unique_requirements"],
        "blocking_requirements": blocking,
        "derived_portability_matches_committed": summary["derived_portability_matches_committed"],
        "status_mismatches": mismatches,
        "validation_passed": summary["validation_passed"],
        "validation_errors": errors,
        "files": [str(req_csv), str(cov_csv), str(summary_json)],
    }, indent=2))
    return 0 if summary["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
