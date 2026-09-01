#!/usr/bin/env python3
"""Emit a LinkML profile for the SOSA terms used in Eautonome.

SOSA records property domains with schema:domainIncludes rather than
rdfs:domain. This script attaches each in-scope property to those classes
and to their subclasses. For example, implementedBy has domain Procedure
and is therefore also attached to ObservingProcedure. rangeIncludes is
stored as documentation only. The profile does not add cardinality
restrictions.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDFS
import yaml

SCHEMA = Namespace("http://schema.org/")
SOSA = Namespace("http://www.w3.org/ns/sosa/")

HERE = Path(__file__).resolve().parent
DEFAULT_SCOPE = HERE / "eautonome-sosa-scope.csv"


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def local(term) -> str:
    return str(term).rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def load_scope(path: Path) -> tuple[list[str], list[str]]:
    classes: list[str] = []
    properties: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["kind"] == "class":
                classes.append(row["term"])
            elif row["kind"] == "property":
                properties.append(row["term"])
    return classes, properties


def load_sosa_graph(ttl_files: list[Path]) -> Graph:
    graph = Graph()
    for path in ttl_files:
        graph.parse(path, format="turtle")
    return graph


def superclass_closure(graph: Graph, class_name: str) -> set[str]:
    start = SOSA[class_name]
    seen: set[URIRef] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for parent in graph.objects(node, RDFS.subClassOf):
            if isinstance(parent, URIRef) and str(parent).startswith(str(SOSA)):
                stack.append(parent)
    seen.discard(start)
    return {local(node) for node in seen}


def build_profile(
    ttl_files: list[Path],
    scope_csv: Path,
    output: Path,
) -> dict:
    used_classes, used_properties = load_scope(scope_csv)
    used_class_set = set(used_classes)
    graph = load_sosa_graph(ttl_files)

    domains: dict[str, list[str]] = {}
    ranges: dict[str, list[str]] = {}
    for name in used_properties:
        pred = SOSA[name]
        domains[name] = sorted({local(obj) for obj in graph.objects(pred, SCHEMA.domainIncludes)})
        ranges[name] = sorted({local(obj) for obj in graph.objects(pred, SCHEMA.rangeIncludes)})

    mixins: dict[str, list[str]] = defaultdict(list)
    for subclass, superclass in graph.subject_objects(RDFS.subClassOf):
        sub_name, super_name = local(subclass), local(superclass)
        if sub_name in used_class_set and super_name in used_class_set:
            mixins[sub_name].append(super_name)

    ancestors = {name: superclass_closure(graph, name) for name in used_classes}

    attachments: list[dict] = []
    class_slots: dict[str, list[str]] = {name: [] for name in used_classes}
    slots: dict = {}
    for name in used_properties:
        slot_id = f"sosa_{snake(name)}"
        range_in_scope = [item for item in ranges[name] if item in used_class_set]
        slot: dict = {
            "slot_uri": f"sosa:{name}",
            "title": re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower(),
            "multivalued": True,
            "notes": [
                "Attached using schema:domainIncludes from the pinned W3C SOSA "
                "modules, including subclasses via rdfs:subClassOf. "
                "schema:rangeIncludes is recorded as documentation only. "
                "No minCount or maxCount is added."
            ],
        }
        comments = []
        if domains[name]:
            comments.append(
                "schema:domainIncludes: " + ", ".join(f"sosa:{item}" for item in domains[name])
            )
        if ranges[name]:
            comments.append(
                "schema:rangeIncludes: " + ", ".join(f"sosa:{item}" for item in ranges[name])
            )
        if range_in_scope:
            comments.append(
                "rangeIncludes classes used in Eautonome, kept as documentation: "
                + ", ".join(range_in_scope)
            )
        inherited_notes = []
        for class_name in used_classes:
            if class_name in domains[name]:
                kind = "direct"
                inherited_from = ""
            else:
                matched = sorted(ancestors[class_name] & set(domains[name]))
                if not matched:
                    continue
                kind = "inherited"
                inherited_from = "|".join(matched)
            class_slots[class_name].append(slot_id)
            attachments.append(
                {
                    "term": name,
                    "slot_id": slot_id,
                    "class": class_name,
                    "association": kind,
                    "inherited_from": inherited_from,
                    "domainIncludes": "|".join(domains[name]),
                    "rangeIncludes": "|".join(ranges[name]),
                }
            )
            if kind == "inherited":
                inherited_notes.append(f"{class_name} via {inherited_from.replace('|', ', ')}")
        if inherited_notes:
            comments.append("inherited associations: " + "; ".join(inherited_notes))
        if comments:
            slot["comments"] = comments
        slots[slot_id] = slot

    classes: dict = {}
    for name in used_classes:
        entry: dict = {
            "class_uri": f"sosa:{name}",
            "title": re.sub(r"(?<!^)(?=[A-Z])", " ", name),
        }
        if mixins[name]:
            entry["mixins"] = [f"Sosa{item}" for item in sorted(set(mixins[name]))]
        if class_slots[name]:
            # preserve first-seen order, unique
            seen: list[str] = []
            for slot_id in class_slots[name]:
                if slot_id not in seen:
                    seen.append(slot_id)
            entry["slots"] = seen
        classes[f"Sosa{name}"] = entry

    schema = {
        "id": "https://w3id.org/eautonome/linkml-sosa-profile",
        "name": "sosa-eautonome",
        "title": "Eautonome SOSA application profile",
        "description": (
            "LinkML application profile for the SOSA terms used in Eautonome. "
            "Slots are attached to classes from schema:domainIncludes in the "
            "pinned W3C SOSA modules, including subclasses via rdfs:subClassOf. "
            "This profile does not replace the Eautonome OWL ontology. "
            "LinkML names are prefixed with Sosa or sosa_ so the profile can "
            "be composed with SAREF-LinkML. class_uri and slot_uri remain the "
            "official SOSA IRIs."
        ),
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "sosa": "http://www.w3.org/ns/sosa/",
            "eau": "https://w3id.org/eautonome/",
        },
        "default_prefix": "sosa",
        "imports": ["linkml:types"],
        "slots": slots,
        "classes": classes,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(schema, handle, sort_keys=False, allow_unicode=True, width=88)

    associations = HERE / "sosa-domainincludes-associations.csv"
    with associations.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "term",
                "slot_id",
                "class",
                "association",
                "inherited_from",
                "domainIncludes",
                "rangeIncludes",
            ],
        )
        writer.writeheader()
        writer.writerows(attachments)
    return schema


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("ttl", nargs="+", type=Path)
    args = parser.parse_args()
    build_profile(args.ttl, args.scope, args.output)
    print(f"wrote {args.output}")
