#!/usr/bin/env python3
"""Remove LinkML-Scala default ranges from SOSA property shapes.

The Eautonome SOSA profile does not declare ranges. LinkML-Scala still emits
xsd:string and sh:Literal when a slot has no range. Those triples are removed
from property shapes whose sh:path is in the SOSA namespace. SAREF-LinkML
shapes are left unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

SH = URIRef("http://www.w3.org/ns/shacl#")
SOSA = "http://www.w3.org/ns/sosa/"


def strip_sosa_default_range(graph: Graph) -> int:
    removed = 0
    datatype = URIRef(str(SH) + "datatype")
    node_kind = URIRef(str(SH) + "nodeKind")
    path = URIRef(str(SH) + "path")
    for prop_shape in set(graph.subjects(path, None)):
        path_value = graph.value(prop_shape, path)
        if path_value is None or not str(path_value).startswith(SOSA):
            continue
        for pred in (datatype, node_kind):
            for obj in list(graph.objects(prop_shape, pred)):
                graph.remove((prop_shape, pred, obj))
                removed += 1
    return removed


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    graph = Graph()
    graph.parse(src, format="turtle")
    removed = strip_sosa_default_range(graph)
    dst.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    print(f"removed {removed} SOSA default-range triples; wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
