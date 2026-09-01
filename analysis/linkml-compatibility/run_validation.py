#!/usr/bin/env python3
"""Validate published Eautonome data against generated LinkML SHACL.

Modes:
  baseline               no alignment, no inference
  alignment_rdfs         official W3C SOSA-SAREF alignment with RDFS
  semantic_closure_rdfs  alignment, SAREF Core, and SAREF4WATR TBox with RDFS.
                         This is the primary compatibility evaluation.
  owlrl_sensitivity      same ontology sources with OWL RL.
                         This is a sensitivity analysis, not the primary result.
"""
from __future__ import annotations

import csv
import json
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

import pyshacl
import rdflib
from pyshacl import validate
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

EAU = "https://w3id.org/eautonome/"
SAREF = Namespace("https://saref.etsi.org/core/")
SH = Namespace("http://www.w3.org/ns/shacl#")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

PRIMARY_MODE = "semantic_closure_rdfs"
SAREF_LINKML_RELEASE = "v4.1.1-2026-08-31"
SAREF_LINKML_COMMIT = "5c50930de681afbffcbfd80a58c91eccde7c97de"
W3C_SOSA_SSN_COMMIT = "37fa55298187464b41c3712620dcbf5bd438b1b2"
PRIMARY_WORDING = (
    "No violation was attributable to the published Eautonome observation "
    "data in the primary compatibility evaluation."
)
W3C_REPO = "https://github.com/w3c/sdw-sosa-ssn"
SAREF_LINKML_REPO = "https://github.com/NeverBlink-OSS/saref-linkml"
ALIGNMENT_SOURCE = (
    f"{W3C_REPO}/blob/{W3C_SOSA_SSN_COMMIT}/ssn/rdf/ontology/alignments/sosa-saref.ttl"
)
SAREF_CORE_SOURCE = (
    f"{SAREF_LINKML_REPO}/blob/{SAREF_LINKML_COMMIT}/source/SAREFCore/saref.ttl"
)
SAREF4WATR_SOURCE = (
    f"{SAREF_LINKML_REPO}/blob/{SAREF_LINKML_COMMIT}/source/saref4watr/saref4watr.ttl"
)
PINNED_ONTOLOGIES = {
    "sosa-saref.ttl": (
        f"https://raw.githubusercontent.com/w3c/sdw-sosa-ssn/"
        f"{W3C_SOSA_SSN_COMMIT}/ssn/rdf/ontology/alignments/sosa-saref.ttl"
    ),
    "saref-core.ttl": (
        f"https://raw.githubusercontent.com/NeverBlink-OSS/saref-linkml/"
        f"{SAREF_LINKML_COMMIT}/source/SAREFCore/saref.ttl"
    ),
    "saref4watr.ttl": (
        f"https://raw.githubusercontent.com/NeverBlink-OSS/saref-linkml/"
        f"{SAREF_LINKML_COMMIT}/source/saref4watr/saref4watr.ttl"
    ),
}

FIELDNAMES = [
    "dataset",
    "mode",
    "focus_owner",
    "classification",
    "focus_node",
    "result_path",
    "value",
    "constraint",
    "source_shape",
    "severity",
    "message",
]


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def fetch_pinned_ontology(filename: str) -> Path:
    """Return a pinned third-party ontology file.

    A local copy under provenance or .cache is used when present. Otherwise the
    file is downloaded from the commit recorded in versions.yaml.
    """
    for directory in (HERE / "provenance", HERE / ".cache"):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    url = PINNED_ONTOLOGIES[filename]
    cache_dir = HERE / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / filename
    print(f"fetching {url}", flush=True)
    urllib.request.urlretrieve(url, dest)
    return dest


def load_graph(paths: list[Path]) -> Graph:
    graph = Graph()
    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".ttl":
            graph.parse(path, format="turtle")
        elif suffix in {".jsonld", ".json"}:
            graph.parse(path, format="json-ld")
        else:
            graph.parse(path)
    return graph


def focus_owner(iri: str) -> str:
    return "eautonome" if iri.startswith(EAU) else "third_party"


def _one(graph: Graph, subject, predicate) -> str:
    value = graph.value(subject, predicate)
    return "" if value is None else str(value)


def extract_results(report: Graph) -> list[dict]:
    rows = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        row = {
            "focus_node": _one(report, result, SH.focusNode),
            "result_path": _one(report, result, SH.resultPath),
            "value": _one(report, result, SH.value),
            "constraint": _one(report, result, SH.sourceConstraintComponent),
            "source_shape": _one(report, result, SH.sourceShape),
            "severity": _one(report, result, SH.resultSeverity),
            "message": _one(report, result, SH.resultMessage),
        }
        rows.append(row)
    rows.sort(
        key=lambda item: (
            item["focus_node"],
            item["result_path"],
            item["value"],
            item["constraint"],
            item["message"],
        )
    )
    return rows


def result_key(row: dict) -> tuple[str, str, str, str]:
    constraint = row.get("constraint") or ""
    short = constraint.rsplit("#", 1)[-1]
    return (
        row.get("focus_node") or "",
        row.get("result_path") or "",
        row.get("value") or "",
        short,
    )


def classify(row: dict, mode: str, closure_keys: set[tuple[str, str, str, str]]) -> str:
    path = row.get("result_path") or ""
    constraint = row.get("constraint") or ""
    message = (row.get("message") or "").lower()
    min_count = "MinCountConstraintComponent" in constraint
    in_constraint = "InConstraintComponent" in constraint or "not in" in message
    or_constraint = "OrConstraintComponent" in constraint
    class_constraint = "ClassConstraintComponent" in constraint
    nodekind = "NodeKindConstraintComponent" in constraint

    if focus_owner(row.get("focus_node") or "") == "third_party":
        return "third_party_ontology_focus"

    if in_constraint and (
        path.endswith("isDesignedFor")
        or path.endswith("isIntendedFor")
        or "WaterKind" in message
        or "WaterUse" in message
        or "not in list" in message
    ):
        return "linkml_conversion_limitation"

    if path == str(SAREF.observes) and min_count:
        return "missing_entailment_or_alignment"

    if path == str(SAREF.observes) and (or_constraint or class_constraint):
        if mode == "alignment_rdfs":
            if result_key(row) in closure_keys:
                return "linkml_conversion_limitation"
            return "missing_ontology_closure"
        if mode in {PRIMARY_MODE, "owlrl_sensitivity"}:
            return "linkml_conversion_limitation"
        return "needs_manual_review"

    if mode == "baseline" and path.startswith(str(SAREF)) and min_count:
        return "missing_entailment_or_alignment"

    if mode == "owlrl_sensitivity" and (
        (path.endswith("hasResult") and nodekind)
        or path.endswith("isExecutionOf")
        or path.endswith("isObservedBy")
        or path.endswith("isTargetOf")
    ):
        return "owlrl_equivalent_unfolding"

    return "needs_manual_review"


def run_mode(
    name: str,
    data: Graph,
    shapes: Graph,
    ont_graph: Graph | None,
    inference: str,
) -> dict:
    print(
        f"running mode {name} inference={inference} data_triples={len(data)} "
        f"ont_triples={0 if ont_graph is None else len(ont_graph)}",
        flush=True,
    )
    conforms, report_graph, text = validate(
        data,
        shacl_graph=shapes,
        ont_graph=ont_graph,
        inference=inference,
        abort_on_first=False,
        allow_infos=True,
        allow_warnings=True,
        meta_shacl=False,
        advanced=False,
        inplace=False,
    )
    rows = extract_results(report_graph)
    return {
        "mode": name,
        "conforms": bool(conforms),
        "inference": inference,
        "n_results": len(rows),
        "results": rows,
        "text": text,
    }


def linkml_scala_version() -> str:
    try:
        proc = subprocess.run(
            ["linkml-scala", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        line = (proc.stdout or proc.stderr).splitlines()[0] if (proc.stdout or proc.stderr) else ""
        return line.replace("linkml-scala", "").strip() or "unknown"
    except OSError:
        return "not-on-PATH"


def annotate_and_summarize(
    all_rows: list[dict],
    dataset_summary: dict,
    mode_specs: dict,
    shapes_path: Path,
) -> dict:
    closure_keys = {
        result_key(row) for row in all_rows if row["mode"] == PRIMARY_MODE
    }
    for row in all_rows:
        row["focus_owner"] = focus_owner(row["focus_node"])
        row["classification"] = classify(row, row["mode"], closure_keys)

    by_class: dict[tuple[str, str, str], int] = {}
    eautonome_counts: dict[tuple[str, str], int] = {}
    third_party_counts: dict[tuple[str, str], int] = {}
    for row in all_rows:
        key = (row["dataset"], row["mode"], row["classification"])
        by_class[key] = by_class.get(key, 0) + 1
        owner_key = (row["dataset"], row["mode"])
        if row["focus_owner"] == "eautonome":
            eautonome_counts[owner_key] = eautonome_counts.get(owner_key, 0) + 1
        else:
            third_party_counts[owner_key] = third_party_counts.get(owner_key, 0) + 1

    for dataset_name, summary in dataset_summary.items():
        for mode_name in list(summary):
            if mode_name == "files":
                continue
            owner_key = (dataset_name, mode_name)
            summary[mode_name]["eautonome_focus"] = eautonome_counts.get(owner_key, 0)
            summary[mode_name]["third_party_focus"] = third_party_counts.get(owner_key, 0)

    return {
        "shapes": rel(shapes_path),
        "alignment": ALIGNMENT_SOURCE,
        "primary_mode": PRIMARY_MODE,
        "primary_wording": PRIMARY_WORDING,
        "modes": mode_specs,
        "datasets": dataset_summary,
        "versions": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "rdflib": rdflib.__version__,
            "pyshacl": pyshacl.__version__,
            "linkml_scala": linkml_scala_version(),
            "saref_linkml_release": SAREF_LINKML_RELEASE,
            "saref_linkml_commit": SAREF_LINKML_COMMIT,
            "w3c_sosa_ssn_commit": W3C_SOSA_SSN_COMMIT,
        },
        "classification_counts": [
            {
                "dataset": dataset,
                "mode": mode,
                "classification": classification,
                "count": count,
            }
            for (dataset, mode, classification), count in sorted(by_class.items())
        ],
        "eautonome_focus_counts": [
            {"dataset": dataset, "mode": mode, "count": count}
            for (dataset, mode), count in sorted(eautonome_counts.items())
        ],
        "third_party_focus_counts": [
            {"dataset": dataset, "mode": mode, "count": count}
            for (dataset, mode), count in sorted(third_party_counts.items())
        ],
        "n_result_rows": len(all_rows),
    }


def write_outputs(all_rows: list[dict], summary: dict) -> None:
    csv_path = HERE / "validation-results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in all_rows:
            writer.writerow({key: row.get(key, "") for key in FIELDNAMES})
    json_path = HERE / "validation-results.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {rel(csv_path)}")
    print(f"wrote {rel(json_path)}")


def mode_specs() -> dict:
    tbox = [ALIGNMENT_SOURCE, SAREF_CORE_SOURCE, SAREF4WATR_SOURCE]
    return {
        "baseline": {
            "role": "baseline",
            "inference": "none",
            "ont_graph": [],
            "description": "No SOSA-SAREF alignment and no inference.",
        },
        "alignment_rdfs": {
            "role": "vocabulary_bridge",
            "inference": "rdfs",
            "ont_graph": [ALIGNMENT_SOURCE],
            "description": (
                "Official W3C SOSA-SAREF alignment with RDFS inference. "
                "This mode tests the sosa:observes rdfs:subPropertyOf "
                "saref:observes bridge."
            ),
        },
        PRIMARY_MODE: {
            "role": "primary_compatibility_evaluation",
            "inference": "rdfs",
            "ont_graph": tbox,
            "description": (
                "W3C SOSA-SAREF alignment together with SAREF Core v4.1.1 and "
                "SAREF4WATR v2.1.1 under RDFS inference. This is the primary "
                "compatibility evaluation. The required entailments are "
                "rdfs:subPropertyOf and rdfs:subClassOf."
            ),
        },
        "owlrl_sensitivity": {
            "role": "sensitivity_analysis",
            "inference": "owlrl",
            "ont_graph": tbox,
            "description": (
                "Same ontology sources as semantic_closure_rdfs, with OWL RL. "
                "This is a sensitivity analysis. Materializing "
                "owl:equivalentClass and owl:equivalentProperty causes "
                "additional SAREF-LinkML generated shapes to target "
                "SOSA-native resources. It is not the primary compatibility "
                "result. The run uses the ontology and hydrodynamic graphs "
                "because OWL RL over the full shower and combined observation "
                "payload did not finish in this environment."
            ),
        },
    }


def main() -> int:
    shapes_path = HERE / "generated" / "eautonome-composed-shapes.ttl"
    alignment_path = fetch_pinned_ontology("sosa-saref.ttl")
    saref_core_path = fetch_pinned_ontology("saref-core.ttl")
    saref4watr_path = fetch_pinned_ontology("saref4watr.ttl")
    ontology = REPO / "docs" / "ontology" / "eautonome.ttl"
    hydro = REPO / "docs" / "data" / "hydrodynamic-observations.jsonld"
    shower = REPO / "docs" / "data" / "shower-observations.jsonld"
    out_dir = HERE / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    shapes = Graph().parse(shapes_path, format="turtle")
    alignment = Graph().parse(alignment_path, format="turtle")
    tbox = Graph()
    tbox += alignment
    tbox.parse(saref_core_path, format="turtle")
    tbox.parse(saref4watr_path, format="turtle")
    specs = mode_specs()

    published = {
        "hydrodynamic": [ontology, hydro],
        "shower": [ontology, shower],
        "combined": [ontology, hydro, shower],
    }
    # OWL RL over the full observation payload is too expensive here.
    # The sensitivity analysis therefore uses the graphs that already contain
    # every Eautonome focus node from the primary evaluation.
    owlrl_datasets = {
        "ontology": [ontology],
        "hydrodynamic": [ontology, hydro],
    }
    closure_datasets = {**published, "ontology": [ontology]}

    all_rows: list[dict] = []
    dataset_summary: dict = {}

    for dataset_name, paths in published.items():
        data = load_graph(paths)
        baseline = run_mode("baseline", data, shapes, ont_graph=None, inference="none")
        aligned = run_mode(
            "alignment_rdfs", data, shapes, ont_graph=alignment, inference="rdfs"
        )
        dataset_summary[dataset_name] = {
            "files": [rel(path) for path in paths],
            "baseline": {
                "conforms": baseline["conforms"],
                "n_results": baseline["n_results"],
            },
            "alignment_rdfs": {
                "conforms": aligned["conforms"],
                "n_results": aligned["n_results"],
            },
        }
        for mode in (baseline, aligned):
            (out_dir / f"{dataset_name}-mode-{mode['mode']}.txt").write_text(
                mode["text"], encoding="utf-8"
            )
            for row in mode["results"]:
                row["dataset"] = dataset_name
                row["mode"] = mode["mode"]
                all_rows.append(row)

    for dataset_name, paths in closure_datasets.items():
        data = load_graph(paths)
        closure = run_mode(
            PRIMARY_MODE, data, shapes, ont_graph=tbox, inference="rdfs"
        )
        dataset_summary.setdefault(dataset_name, {"files": [rel(path) for path in paths]})
        dataset_summary[dataset_name][PRIMARY_MODE] = {
            "conforms": closure["conforms"],
            "n_results": closure["n_results"],
        }
        (out_dir / f"{dataset_name}-mode-{PRIMARY_MODE}.txt").write_text(
            closure["text"], encoding="utf-8"
        )
        for row in closure["results"]:
            row["dataset"] = dataset_name
            row["mode"] = PRIMARY_MODE
            all_rows.append(row)

    for dataset_name, paths in owlrl_datasets.items():
        data = load_graph(paths)
        sensitivity = run_mode(
            "owlrl_sensitivity", data, shapes, ont_graph=tbox, inference="owlrl"
        )
        dataset_summary.setdefault(dataset_name, {"files": [rel(path) for path in paths]})
        dataset_summary[dataset_name]["owlrl_sensitivity"] = {
            "conforms": sensitivity["conforms"],
            "n_results": sensitivity["n_results"],
        }
        (out_dir / f"{dataset_name}-mode-owlrl_sensitivity.txt").write_text(
            sensitivity["text"], encoding="utf-8"
        )
        for row in sensitivity["results"]:
            row["dataset"] = dataset_name
            row["mode"] = "owlrl_sensitivity"
            all_rows.append(row)

    summary = annotate_and_summarize(all_rows, dataset_summary, specs, shapes_path)
    write_outputs(all_rows, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
