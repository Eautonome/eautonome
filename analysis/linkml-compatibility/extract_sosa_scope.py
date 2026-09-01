#!/usr/bin/env python3
"""Collect SOSA and SSN terms from published Eautonome RDF.

The ontology and the example datasets are parsed as RDF. Terms are then
checked against the pinned W3C SOSA modules when those files are supplied.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS
import yaml

SOSA_NS = "http://www.w3.org/ns/sosa/"
SSN_NS = "http://www.w3.org/ns/ssn/"
SKIP_LOCAL = {"", "common", "obs", "sam", "act", "systems", "saref"}

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def local(term: URIRef) -> str:
    return str(term).rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def parse_input(path: Path) -> Graph:
    graph = Graph()
    suffix = path.suffix.lower()
    if suffix == ".ttl":
        graph.parse(path, format="turtle")
    elif suffix in {".jsonld", ".json"}:
        graph.parse(path, format="json-ld")
    else:
        graph.parse(path)
    return graph


def sosa_iris(graph: Graph) -> Counter:
    counts: Counter = Counter()
    for subj, pred, obj in graph:
        for node in (subj, pred, obj):
            if isinstance(node, URIRef) and str(node).startswith(SOSA_NS):
                name = local(node)
                if name not in SKIP_LOCAL:
                    counts[str(node)] += 1
    return counts


def classify_term(iri: str, w3c: Graph, usage: Graph) -> str:
    node = URIRef(iri)
    if (node, RDF.type, OWL.Class) in w3c or (node, RDF.type, RDFS.Class) in w3c:
        return "class"
    if (node, RDF.type, OWL.ObjectProperty) in w3c or (node, RDF.type, OWL.DatatypeProperty) in w3c:
        return "property"
    if any(True for _ in usage.subjects(RDF.type, node)):
        return "class"
    if any(True for _ in usage.triples((None, node, None))):
        return "property"
    return "term"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--w3c", nargs="+", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--yaml", type=Path, required=True)
    args = parser.parse_args()

    combined = Graph()
    per_file: dict[str, Counter] = {}
    for path in args.inputs:
        graph = parse_input(path)
        combined += graph
        rel = path if path.is_absolute() else path
        try:
            rel_s = str(path.resolve().relative_to(REPO))
        except ValueError:
            rel_s = str(path)
        per_file[rel_s] = sosa_iris(graph)

    total = sosa_iris(combined)
    w3c = Graph()
    for path in args.w3c:
        w3c.parse(path, format="turtle")

    ssn_count = 0
    for subj, pred, obj in combined:
        for node in (subj, pred, obj):
            if isinstance(node, URIRef) and str(node).startswith(SSN_NS):
                ssn_count += 1

    rows = []
    for iri, count in sorted(total.items(), key=lambda item: local(URIRef(item[0])).lower()):
        kind = classify_term(iri, w3c, combined)
        name = local(URIRef(iri))
        files = [name_ for name_, counter in per_file.items() if iri in counter]
        rows.append(
            {
                "term": name,
                "kind": kind,
                "occurrences": count,
                "iri": iri,
                "in_files": "|".join(files),
            }
        )

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["term", "kind", "occurrences", "iri", "in_files"]
        )
        writer.writeheader()
        writer.writerows(rows)

    classes = sorted(row["term"] for row in rows if row["kind"] == "class")
    properties = sorted(row["term"] for row in rows if row["kind"] == "property")
    payload = {
        "sosa_scope": {
            "source": "Published Eautonome ontology plus example datasets, parsed as RDF",
            "inputs": [str(Path(p).resolve().relative_to(REPO)) if Path(p).is_absolute() else str(p) for p in args.inputs],
            "distinct_terms": len(rows),
            "classes": classes,
            "properties": properties,
            "explicit_ssn_namespace_terms": ssn_count,
        }
    }
    args.yaml.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"distinct SOSA terms: {len(rows)}")
    print(f"classes: {len(classes)}")
    print(f"properties: {len(properties)}")
    print(f"wrote {args.csv}")
    print(f"wrote {args.yaml}")
    for row in rows:
        print(f"  {row['kind']}\t{row['term']}\t{row['occurrences']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
