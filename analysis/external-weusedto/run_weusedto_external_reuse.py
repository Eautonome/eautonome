#!/usr/bin/env python3
"""Map WEUSEDTO CSVs to Eautonome instance data (external reuse check).

Pass the path to an external WEUSEDTO data/ directory. Source CSVs are not shipped here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD
from rdflib.compare import to_isomorphic
from rdflib.namespace import DCTERMS, OWL

SOSA = Namespace("http://www.w3.org/ns/sosa/")
EAU = Namespace("https://w3id.org/eautonome/")
S4WATR = Namespace("https://saref.etsi.org/saref4watr/")
TIME = Namespace("http://www.w3.org/2006/time#")
SCHEMA = Namespace("http://schema.org/")

WEUSEDTO_REPO = "https://github.com/Water-End-Use-Dataset-Tools/WEUSEDTO"
WEUSEDTO_DOI = "https://doi.org/10.1016/j.softx.2022.101214"
WEUSEDTO_ZENODO = "https://doi.org/10.5281/zenodo.4651443"
DATASET_IRI = EAU.weusedtoDataset

DOCUMENTED_SERIES = {
    "Washbasin": {"format": "A", "patterns": ["feed_Washbasin.MYD.csv"]},
    "Bidet": {"format": "A", "patterns": ["feed_Bidet.MYD.csv"]},
    "Kitchenfaucet": {"format": "A", "patterns": ["feed_Kitchenfaucet.MYD.csv"]},
    "Shower": {"format": "A", "patterns": ["feed_Shower.MYD.csv"]},
    "Washingmachine": {"format": "A", "patterns": ["feed_Washingmachine.MYD.csv"]},
    "Dishwasher30": {"format": "B", "patterns": ["feed_Dishwasher30.MYD.csv"]},
    "Dishwasher50eco": {"format": "B", "patterns": ["feed_Dishwasher50eco.MYD.csv", "feed_Dishwasher50.MYD.csv"]},
    "Toilet": {"format": "B", "patterns": ["feed.Toilet.csv", "feed_Toilet.MYD.csv", "feed_Toilet.csv"]},
    "WholeHouse": {"format": "A", "patterns": ["feed_WholeHouse.MYD.csv"]},
}

EXTREME_ABS_FLOW = Decimal("1000000")  # QA flag only

TIMESTAMP_NOTE = "Epochs treated as UTC. Source CSV has no timezone field."
FORMAT_A_RESULTTIME_NOTE = (
    "Format A: sample epoch stored as sosa:resultTime."
)
UNIT_NOTE = (
    "Docs say ml/s, but liters() does flow*dt with no /1000, there is no QUDT unit. "
)
FORMAT_B_FLOW_NOTE = "Format B Flow is a single value per interval."

TERMS_NOT_ASSERTED = [
    "eau:DomesticRoom",
    "eau:locatedIn",
    "eau:servesEndpoint",
    "eau:measuresWaterKind",
    "s4watr:WaterUse",
    "s4watr:FlowVolume",
    "MYD splitter ConsumptionEvent",
    "Format B sosa:resultTime",
    "QUDT unit on FlowRate",
    "eau typed sensor subclasses",
]

ALLOWED_EAU_CLASSES = {
    EAU.MeasurementPoint,
    EAU.ConsumptionEvent,
}

ONTOLOGY_RELATIVE_PATH = "docs/ontology/eautonome.ttl"


def slug(series: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", series)


def sensor_iri(series: str) -> URIRef:
    return EAU[f"weusedtoSensor{slug(series)}"]


def mp_iri(series: str) -> URIRef:
    return EAU[f"weusedtoMeasurementPoint{slug(series)}"]


def obs_iri(series: str, index: int) -> URIRef:
    return EAU[f"weusedtoObs{slug(series)}{index:06d}"]


def event_iri(series: str, index: int) -> URIRef:
    return EAU[f"weusedtoEvent{slug(series)}{index:06d}"]


def collection_iri(series: str, index: int) -> URIRef:
    return EAU[f"weusedtoCollection{slug(series)}{index:06d}"]


def child_iri(owner: URIRef, *parts: str) -> URIRef:
    """Deterministic IRI for interval/instant resources owned by an event/collection/observation."""
    return URIRef(str(owner) + "/" + "/".join(parts))


def utc_lexical(epoch: float) -> str:
    if not math.isfinite(epoch):
        raise ValueError(f"non-finite epoch for datetime conversion: {epoch!r}")
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_finite_number(value: float) -> bool:
    return not isinstance(value, bool) and math.isfinite(value)


def is_finite_decimal(value: Decimal) -> bool:
    return value.is_finite()


def add_common_prefixes(g: Graph) -> None:
    g.bind("sosa", SOSA)
    g.bind("eau", EAU)
    g.bind("s4watr", S4WATR)
    g.bind("time", TIME)
    g.bind("schema", SCHEMA)
    g.bind("dcterms", DCTERMS)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)


def add_dataset_provenance(g: Graph) -> None:
    g.add((DATASET_IRI, RDF.type, SCHEMA.Dataset))
    g.add((DATASET_IRI, RDFS.label, Literal("WEUSEDTO water end-use dataset")))
    g.add((DATASET_IRI, DCTERMS.title, Literal("WEUSEDTO Water End USE Dataset and TOols")))
    g.add((DATASET_IRI, DCTERMS.source, URIRef(WEUSEDTO_REPO)))
    g.add((DATASET_IRI, DCTERMS.identifier, Literal(WEUSEDTO_DOI)))
    g.add((DATASET_IRI, RDFS.comment, Literal(
        "Mapped WEUSEDTO subset (CC BY 4.0). Full CSVs stay upstream."
    )))


def add_static_series(g: Graph, series: str, label: str) -> Tuple[URIRef, URIRef]:
    s = sensor_iri(series)
    mp = mp_iri(series)
    g.add((s, RDF.type, SOSA.Sensor))
    g.add((s, RDFS.label, Literal(f"WEUSEDTO {label} sensor")))
    g.add((s, EAU.monitors, mp))
    g.add((s, SOSA.observes, S4WATR.FlowRate))
    g.add((s, DCTERMS.source, DATASET_IRI))

    g.add((mp, RDF.type, EAU.MeasurementPoint))
    g.add((mp, RDFS.label, Literal(f"WEUSEDTO {label} measurement point")))
    g.add((mp, DCTERMS.source, DATASET_IRI))
    return s, mp


def add_interval(g: Graph, subject: URIRef, predicate, start_epoch: float, end_epoch: float) -> None:
    interval = child_iri(subject, "phenomenonTime")
    begin = child_iri(subject, "phenomenonTime", "begin")
    end = child_iri(subject, "phenomenonTime", "end")
    g.add((subject, predicate, interval))
    g.add((interval, RDF.type, TIME.Interval))
    g.add((interval, TIME.hasBeginning, begin))
    g.add((interval, TIME.hasEnd, end))
    g.add((begin, RDF.type, TIME.Instant))
    g.add((end, RDF.type, TIME.Instant))
    g.add((begin, TIME.inXSDDateTime, Literal(utc_lexical(start_epoch), datatype=XSD.dateTime)))
    g.add((end, TIME.inXSDDateTime, Literal(utc_lexical(end_epoch), datatype=XSD.dateTime)))


def add_event_bounds(g: Graph, event: URIRef, start_epoch: float, end_epoch: float) -> None:
    begin = child_iri(event, "begin")
    end = child_iri(event, "end")
    g.add((event, TIME.hasBeginning, begin))
    g.add((event, TIME.hasEnd, end))
    g.add((begin, RDF.type, TIME.Instant))
    g.add((end, RDF.type, TIME.Instant))
    g.add((begin, TIME.inXSDDateTime, Literal(utc_lexical(start_epoch), datatype=XSD.dateTime)))
    g.add((end, TIME.inXSDDateTime, Literal(utc_lexical(end_epoch), datatype=XSD.dateTime)))


def flow_literal_from_source(lexical: str) -> Literal:
    """xsd:decimal literal preserving the exact CSV lexical form (no float round-trip)."""
    return Literal(lexical, datatype=XSD.decimal)


def duration_seconds_literal(duration: Decimal) -> Literal:
    """Consistent xsd:decimal lexical form that round-trips Turtle and JSON-LD identically."""
    if not duration.is_finite():
        raise ValueError(f"non-finite duration: {duration!r}")
    if duration == duration.to_integral_value():
        # e.g. 1800.0 / 360.0 so Turtle and JSON-LD match
        return Literal(f"{duration:.1f}", datatype=XSD.decimal)
    text = format(duration, "f").rstrip("0").rstrip(".")
    if "." not in text:
        text = f"{text}.0"
    return Literal(text, datatype=XSD.decimal)


@dataclass
class FileStats:
    series: str
    filename: str
    format: str  # A | B
    rows_total: int = 0
    rows_used: int = 0
    observations: int = 0
    events: int = 0
    collections: int = 0
    min_epoch: Optional[float] = None
    max_epoch: Optional[float] = None
    negative_values: int = 0
    nonfinite_values: int = 0
    invalid_rows: int = 0
    extreme_values: int = 0
    gaps: List[float] = field(default_factory=list)

    def note_epoch(self, epoch: float) -> None:
        if self.min_epoch is None or epoch < self.min_epoch:
            self.min_epoch = epoch
        if self.max_epoch is None or epoch > self.max_epoch:
            self.max_epoch = epoch

    def gap_stats(self) -> dict:
        if not self.gaps:
            return {
                "gap_count": 0,
                "gap_median_seconds": None,
                "gap_mean_seconds": None,
                "gap_min_seconds": None,
                "gap_max_seconds": None,
                "gap_eq_1s_count": 0,
                "gap_near_301s_count": 0,
            }
        near_301 = sum(1 for g in self.gaps if 295 <= g <= 305)
        return {
            "gap_count": len(self.gaps),
            "gap_median_seconds": statistics.median(self.gaps),
            "gap_mean_seconds": statistics.fmean(self.gaps),
            "gap_min_seconds": min(self.gaps),
            "gap_max_seconds": max(self.gaps),
            "gap_eq_1s_count": sum(1 for g in self.gaps if abs(g - 1.0) < 1e-9),
            "gap_near_301s_count": near_301,
        }


def resolve_series_files(data_dir: Path) -> Tuple[Dict[str, Path], List[str], List[str]]:
    """Return (series->path, missing_documented, discovered_unmapped)."""
    found = {p.name: p for p in sorted(data_dir.glob("*.csv"))}
    discovered = sorted(found)
    series_paths: Dict[str, Path] = {}
    missing: List[str] = []
    claimed = set()
    for series, meta in DOCUMENTED_SERIES.items():
        path = None
        for pattern in meta["patterns"]:
            if pattern in found:
                path = found[pattern]
                claimed.add(pattern)
                break
        if path is None:
            missing.append(series)
        else:
            series_paths[series] = path
    unmapped = [name for name in discovered if name not in claimed]
    return series_paths, missing, unmapped


def parse_format_a(path: Path) -> Iterable[Tuple[str, Optional[Tuple[float, Decimal, str]]]]:
    """Yield ('ok', (epoch, flow_decimal, flow_lexical)) or ('invalid', None)."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                yield ("invalid", None)
                continue
            try:
                epoch = float(parts[0])
                flow_lex = parts[1]
                flow = Decimal(flow_lex)
            except (ValueError, InvalidOperation):
                yield ("invalid", None)
                continue
            yield ("ok", (epoch, flow, flow_lex))


def parse_format_b(
    path: Path,
) -> Iterable[Tuple[str, Optional[Tuple[float, Decimal, str, float, Decimal]]]]:
    """Yield ('ok', (start, flow, flow_lex, end, duration)) or ('invalid', None).

    Flow keeps the exact CSV lexical form. Duration is Decimal(end) - Decimal(start).
    """
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        first = True
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            if first and re.search(r"[A-Za-z]", raw):
                first = False
                continue
            first = False
            parts = re.split(r"\s+", raw)
            if len(parts) < 3:
                yield ("invalid", None)
                continue
            try:
                start_d = Decimal(parts[0])
                flow_lex = parts[1]
                flow = Decimal(flow_lex)
                end_d = Decimal(parts[2])
                start = float(start_d)
                end = float(end_d)
                duration = end_d - start_d
            except (ValueError, InvalidOperation, OverflowError):
                yield ("invalid", None)
                continue
            yield ("ok", (start, flow, flow_lex, end, duration))


def process_format_a(
    series: str,
    path: Path,
    full_graph: Optional[Graph],
    example_graph: Graph,
    example_limit: int,
) -> FileStats:
    stats = FileStats(series=series, filename=path.name, format="A")
    label = series
    if full_graph is not None:
        add_static_series(full_graph, series, label)
    add_static_series(example_graph, series, label)

    prev_epoch: Optional[float] = None
    for status, payload in parse_format_a(path):
        stats.rows_total += 1
        if status != "ok" or payload is None:
            stats.invalid_rows += 1
            continue
        epoch, flow, flow_lex = payload
        if not is_finite_number(epoch):
            stats.invalid_rows += 1
            continue
        if not is_finite_decimal(flow):
            stats.nonfinite_values += 1
            continue

        stats.note_epoch(epoch)
        if prev_epoch is not None:
            stats.gaps.append(epoch - prev_epoch)
        prev_epoch = epoch

        if flow < 0:
            stats.negative_values += 1
        if abs(flow) >= EXTREME_ABS_FLOW:
            stats.extreme_values += 1

        stats.rows_used += 1
        stats.observations += 1
        idx = stats.observations
        include_example = idx <= example_limit
        targets = []
        if full_graph is not None:
            targets.append(full_graph)
        if include_example:
            targets.append(example_graph)
        for g in targets:
            obs = obs_iri(series, idx)
            g.add((obs, RDF.type, SOSA.Observation))
            g.add((obs, SOSA.madeBySensor, sensor_iri(series)))
            g.add((obs, SOSA.hasFeatureOfInterest, mp_iri(series)))
            g.add((obs, SOSA.observedProperty, S4WATR.FlowRate))
            g.add((obs, SOSA.hasSimpleResult, flow_literal_from_source(flow_lex)))
            g.add((obs, SOSA.resultTime, Literal(utc_lexical(epoch), datatype=XSD.dateTime)))
    return stats


def process_format_b(
    series: str,
    path: Path,
    full_graph: Optional[Graph],
    example_graph: Graph,
    example_limit: int,
) -> FileStats:
    stats = FileStats(series=series, filename=path.name, format="B")
    label = series
    if full_graph is not None:
        add_static_series(full_graph, series, label)
    add_static_series(example_graph, series, label)

    prev_start: Optional[float] = None
    for status, payload in parse_format_b(path):
        stats.rows_total += 1
        if status != "ok" or payload is None:
            stats.invalid_rows += 1
            continue
        start, flow, flow_lex, end, duration = payload
        if not is_finite_number(start) or not is_finite_number(end):
            stats.invalid_rows += 1
            continue
        if not is_finite_decimal(flow) or not is_finite_decimal(duration):
            stats.nonfinite_values += 1
            continue
        if end < start:
            stats.invalid_rows += 1
            continue

        stats.note_epoch(start)
        stats.note_epoch(end)
        if prev_start is not None:
            stats.gaps.append(start - prev_start)
        prev_start = start

        if flow < 0:
            stats.negative_values += 1
        if abs(flow) >= EXTREME_ABS_FLOW:
            stats.extreme_values += 1

        stats.rows_used += 1
        stats.events += 1
        stats.collections += 1
        stats.observations += 1
        idx = stats.events
        include_example = idx <= example_limit
        targets = []
        if full_graph is not None:
            targets.append(full_graph)
        if include_example:
            targets.append(example_graph)

        for g in targets:
            event = event_iri(series, idx)
            coll = collection_iri(series, idx)
            obs = obs_iri(series, idx)

            g.add((event, RDF.type, EAU.ConsumptionEvent))
            g.add((event, RDFS.label, Literal(f"WEUSEDTO {label} usage {idx}")))
            add_event_bounds(g, event, start, end)

            g.add((coll, RDF.type, SOSA.ObservationCollection))
            g.add((coll, RDFS.label, Literal(f"WEUSEDTO {label} collection {idx}")))
            g.add((coll, SOSA.madeBySensor, sensor_iri(series)))
            g.add((coll, SOSA.hasFeatureOfInterest, mp_iri(series)))
            g.add((coll, SOSA.observedProperty, S4WATR.FlowRate))
            g.add((coll, EAU.hasConsumptionEvent, event))
            add_interval(g, coll, SOSA.phenomenonTime, start, end)
            g.add((coll, SOSA.hasMember, obs))

            g.add((obs, RDF.type, SOSA.Observation))
            g.add((obs, SOSA.madeBySensor, sensor_iri(series)))
            g.add((obs, SOSA.hasFeatureOfInterest, mp_iri(series)))
            g.add((obs, SOSA.observedProperty, S4WATR.FlowRate))
            g.add((obs, SOSA.hasSimpleResult, flow_literal_from_source(flow_lex)))
            # No sosa:resultTime for Format B (interval only in source).
            g.add((obs, EAU.hasDurationSeconds, duration_seconds_literal(duration)))
            add_interval(g, obs, SOSA.phenomenonTime, start, end)
    return stats


def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ontology_catalog(ontology_path: Path) -> Tuple[Set[URIRef], Set[URIRef]]:
    """Return (eau properties, eau classes) declared in the ontology TBox."""
    g = Graph()
    g.parse(ontology_path, format="turtle")
    property_types = {
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
        OWL.FunctionalProperty,
        OWL.InverseFunctionalProperty,
        OWL.SymmetricProperty,
        OWL.TransitiveProperty,
        RDF.Property,
    }
    props: Set[URIRef] = set()
    classes: Set[URIRef] = set()
    for s, _, o in g.triples((None, RDF.type, None)):
        if not isinstance(s, URIRef) or not str(s).startswith(str(EAU)):
            continue
        if o in property_types:
            props.add(s)
        if o in (OWL.Class, RDFS.Class):
            classes.add(s)
    for s, p, o in g:
        if p == OWL.inverseOf:
            if isinstance(s, URIRef) and str(s).startswith(str(EAU)):
                props.add(s)
            if isinstance(o, URIRef) and str(o).startswith(str(EAU)):
                props.add(o)
    return props, classes


def validate_graph(
    g: Graph,
    eau_properties: Set[URIRef],
    eau_classes: Set[URIRef],
) -> List[str]:
    errors: List[str] = []
    forbidden_sensor_types = {
        EAU.VortexFlowmeter,
        EAU.ShowerSensor,
        EAU.ConductivityTemperatureSensor,
    }
    for s, p, o in g:
        if isinstance(p, URIRef) and str(p).startswith(str(EAU)):
            if p not in eau_properties:
                errors.append(f"invented eau predicate not in ontology: {p}")
        if p in (EAU.locatedIn, EAU.servesEndpoint, EAU.measuresWaterKind):
            errors.append(f"prohibited predicate {p} on {s}")
        if p == SOSA.observedProperty and o == S4WATR.FlowVolume:
            errors.append(f"prohibited FlowVolume observedProperty on {s}")
        if p == RDF.type and o in (EAU.DomesticRoom, S4WATR.WaterUse, S4WATR.FlowVolume):
            errors.append(f"prohibited type {o} on {s}")
        if p == RDF.type and o in forbidden_sensor_types:
            errors.append(f"typed eau sensor subclass used: {o} on {s}")
        if p == RDF.type and isinstance(o, URIRef) and str(o).startswith(str(EAU)):
            if o not in ALLOWED_EAU_CLASSES:
                errors.append(f"disallowed eau class typed in this evaluation: {o}")
            elif o not in eau_classes:
                errors.append(f"eau class typed but missing from ontology catalog: {o}")
        if p == SOSA.phenomenonTime and (s, RDF.type, SOSA.Observation) in g:
            if (s, SOSA.resultTime, None) in g:
                errors.append(f"Format-B-style observation has invented sosa:resultTime: {s}")
    return errors


def ontology_checksum(path: Path) -> str:
    return file_checksum(path)


def graph_canonical_digest(g: Graph) -> str:
    """Stable digest over RDF graph content (isomorphism-aware)."""
    iso = to_isomorphic(g)
    nt = iso.serialize(format="nt")
    if isinstance(nt, bytes):
        nt = nt.decode("utf-8")
    lines = sorted(line for line in nt.splitlines() if line.strip())
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def count_types(g: Graph) -> dict:
    return {
        "observations": sum(1 for _ in g.triples((None, RDF.type, SOSA.Observation))),
        "consumption_events": sum(1 for _ in g.triples((None, RDF.type, EAU.ConsumptionEvent))),
        "observation_collections": sum(
            1 for _ in g.triples((None, RDF.type, SOSA.ObservationCollection))
        ),
    }


def build_summary(
    series_paths: Dict[str, Path],
    missing: List[str],
    unmapped: List[str],
    stats_list: List[FileStats],
    example_graph: Graph,
    ontology_path: Path,
    ontology_sha_before: str,
    validation_errors: List[str],
    deterministic_hash: str,
    source_filenames: List[str],
    full_graph_built: bool,
) -> dict:
    per_file = []
    for st in stats_list:
        entry = {
            "series": st.series,
            "filename": st.filename,
            "format": st.format,
            "rows_total": st.rows_total,
            "rows_used": st.rows_used,
            "observations_mapped": st.observations,
            "consumption_events_mapped": st.events,
            "observation_collections_mapped": st.collections,
            "min_timestamp_utc": utc_lexical(st.min_epoch) if st.min_epoch is not None else None,
            "max_timestamp_utc": utc_lexical(st.max_epoch) if st.max_epoch is not None else None,
            "negative_values": st.negative_values,
            "nonfinite_values": st.nonfinite_values,
            "invalid_rows": st.invalid_rows,
            "extreme_abs_ge_1e6": st.extreme_values,
            "sampling_gaps": st.gap_stats(),
            "sha256": file_checksum(series_paths[st.series]),
        }
        per_file.append(entry)

    ontology_sha_after = ontology_checksum(ontology_path)
    example_counts = count_types(example_graph)
    validation_scope = {
        "source_row_qa": "all processed CSV rows",
        "mapping_counts": "row counts for the mapping",
        "example_graph_ontology_checks": True,
        "example_ttl_jsonld_isomorphic": True,
        "example_rebuild_deterministic": True,
        "full_graph_in_memory": bool(full_graph_built),
    }
    return {
        "evaluation": "WEUSEDTO external reuse",
        "evaluation_question": (
            "How much of WEUSEDTO can the current Eautonome ontology cover without changes?"
        ),
        "source_data_dir": "external WEUSEDTO data/ path (runtime argument)",
        "source_files_discovered": source_filenames,
        "source_files_processed": [st.filename for st in stats_list],
        "missing_documented_series": missing,
        "unmapped_discovered_csv": unmapped,
        "sensors_minted": len(stats_list),
        "measurement_points_minted": len(stats_list),
        "format_a_rows_mapped_as_observations": sum(
            st.observations for st in stats_list if st.format == "A"
        ),
        "format_b_rows_mapped_as_observations": sum(
            st.observations for st in stats_list if st.format == "B"
        ),
        "total_source_rows_mapped_as_observations": sum(st.observations for st in stats_list),
        "native_consumption_events_mapped": sum(st.events for st in stats_list),
        "observation_collections_mapped": sum(st.collections for st in stats_list),
        "full_graph_built": full_graph_built,
        "example_observations_serialized": example_counts["observations"],
        "example_consumption_events_serialized": example_counts["consumption_events"],
        "example_observation_collections_serialized": example_counts["observation_collections"],
        "per_file": per_file,
        "negative_value_counts_total": sum(st.negative_values for st in stats_list),
        "nonfinite_invalid_value_counts_total": sum(st.nonfinite_values + st.invalid_rows for st in stats_list),
        "extreme_value_qa_total_abs_ge_1e6": sum(st.extreme_values for st in stats_list),
        "unit_note": UNIT_NOTE,
        "timestamp_note": TIMESTAMP_NOTE,
        "format_a_result_time_note": FORMAT_A_RESULTTIME_NOTE,
        "format_b_flow_note": FORMAT_B_FLOW_NOTE,
        "terms_not_asserted": TERMS_NOT_ASSERTED,
        "ontology_path": ONTOLOGY_RELATIVE_PATH,
        "ontology_sha256_before": ontology_sha_before,
        "ontology_sha256_after": ontology_sha_after,
        "ontology_schema_changed": ontology_sha_before != ontology_sha_after,
        "example_graph_triples": len(example_graph),
        "example_subset_policy": {
            "format_a_observations_per_series": "first N rows (CLI --example-myd-per-series)",
            "format_b_events_per_series": "first N rows (CLI --example-events-per-series)",
        },
        "validation_scope": validation_scope,
        "validation_errors": validation_errors,
        "validation_passed": len(validation_errors) == 0 and ontology_sha_before == ontology_sha_after,
        "deterministic_graph_digest": deterministic_hash,
        "provenance": {
            "repository": WEUSEDTO_REPO,
            "paper_doi": WEUSEDTO_DOI,
            "zenodo_doi": WEUSEDTO_ZENODO,
        },
    }


def mapping_run_rows(stats_list: List[FileStats], missing: List[str]) -> List[dict]:
    rows = []
    for st in stats_list:
        rows.append({
            "series": st.series,
            "filename": st.filename,
            "format": st.format,
            "status": "PROCESSED",
            "sensor_iri": str(sensor_iri(st.series)),
            "measurement_point_iri": str(mp_iri(st.series)),
            "measurement_point_mapping_status": "PARTIAL",
            "observations_mapped": st.observations,
            "consumption_events_mapped": st.events,
            "observation_collections_mapped": st.collections,
            "flow_volume_asserted": False,
            "myd_splitter_events_asserted": False,
            "unit_asserted": False,
            "notes": (
                f"{UNIT_NOTE} {FORMAT_A_RESULTTIME_NOTE}"
                if st.format == "A"
                else FORMAT_B_FLOW_NOTE
            ),
        })
    for series in missing:
        rows.append({
            "series": series,
            "filename": "",
            "format": DOCUMENTED_SERIES[series]["format"],
            "status": "NOT_AVAILABLE",
            "sensor_iri": "",
            "measurement_point_iri": "",
            "measurement_point_mapping_status": "PARTIAL" if series != "Dishwasher50eco" else "NOT_AVAILABLE",
            "observations_mapped": 0,
            "consumption_events_mapped": 0,
            "observation_collections_mapped": 0,
            "flow_volume_asserted": False,
            "myd_splitter_events_asserted": False,
            "unit_asserted": False,
            "notes": "Listed upstream",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "data_dir",
        type=Path,
        help="External WEUSEDTO data directory containing feed_*.csv / feed.Toilet.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        help="Directory for summary.json, mapping-run.csv, and example RDF",
    )
    parser.add_argument(
        "--ontology",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs" / "ontology" / "eautonome.ttl",
        help="Path to eautonome.ttl (read-only checksum guard)",
    )
    parser.add_argument(
        "--example-myd-per-series",
        type=int,
        default=5,
        help="How many Format A observations per series to include in example RDF",
    )
    parser.add_argument(
        "--example-events-per-series",
        type=int,
        default=3,
        help="How many Format B events per series to include in example RDF",
    )
    parser.add_argument(
        "--build-full-graph",
        action="store_true",
        help="Also build an in-memory full graph for validation",
    )
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir.is_dir():
        raise SystemExit(f"data directory not found: {data_dir}")
    ontology_path = args.ontology
    if not ontology_path.is_file():
        raise SystemExit(f"ontology not found: {ontology_path}")

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    ontology_sha_before = ontology_checksum(ontology_path)
    eau_properties, eau_classes = load_ontology_catalog(ontology_path)

    series_paths, missing, unmapped = resolve_series_files(data_dir)
    source_filenames = sorted(p.name for p in data_dir.glob("*.csv"))
    example_graph = Graph()
    add_common_prefixes(example_graph)
    add_dataset_provenance(example_graph)
    full_graph: Optional[Graph] = None
    if args.build_full_graph:
        full_graph = Graph()
        add_common_prefixes(full_graph)
        add_dataset_provenance(full_graph)

    stats_list: List[FileStats] = []
    # Deterministic series order
    for series in sorted(series_paths.keys(), key=lambda s: (DOCUMENTED_SERIES[s]["format"], s)):
        path = series_paths[series]
        fmt = DOCUMENTED_SERIES[series]["format"]
        if fmt == "A":
            stats_list.append(
                process_format_a(
                    series, path, full_graph, example_graph, args.example_myd_per_series
                )
            )
        else:
            stats_list.append(
                process_format_b(
                    series, path, full_graph, example_graph, args.example_events_per_series
                )
            )

    validation_errors: List[str] = []
    for st in stats_list:
        if st.format == "B" and st.events != st.rows_used:
            validation_errors.append(
                f"{st.series}: Format B events {st.events} != rows_used {st.rows_used}"
            )

    validation_errors.extend(validate_graph(example_graph, eau_properties, eau_classes))
    if full_graph is not None:
        validation_errors.extend(validate_graph(full_graph, eau_properties, eau_classes))

    ttl_path = out / "weusedto-example.ttl"
    jsonld_path = out / "weusedto-example.jsonld"
    example_graph.serialize(destination=str(ttl_path), format="turtle")
    example_graph.serialize(destination=str(jsonld_path), format="json-ld", indent=2, auto_compact=True)

    # Re-parse outputs and require isomorphic graphs
    parsed: Dict[str, Graph] = {}
    for path, fmt in [(ttl_path, "turtle"), (jsonld_path, "json-ld")]:
        g = Graph()
        try:
            g.parse(path, format=fmt)
        except Exception as exc:  # noqa: BLE001
            validation_errors.append(f"failed to parse {path.name}: {exc}")
        else:
            validation_errors.extend(validate_graph(g, eau_properties, eau_classes))
            parsed[path.name] = g

    if "weusedto-example.ttl" in parsed and "weusedto-example.jsonld" in parsed:
        if to_isomorphic(parsed["weusedto-example.ttl"]) != to_isomorphic(
            parsed["weusedto-example.jsonld"]
        ):
            validation_errors.append(
                "TTL and JSON-LD example artefacts are not strictly RDF-isomorphic"
            )

    digest1 = graph_canonical_digest(example_graph)

    example_graph_2 = Graph()
    add_common_prefixes(example_graph_2)
    add_dataset_provenance(example_graph_2)
    for st in stats_list:
        path = series_paths[st.series]
        if st.format == "A":
            process_format_a(st.series, path, None, example_graph_2, args.example_myd_per_series)
        else:
            process_format_b(st.series, path, None, example_graph_2, args.example_events_per_series)
    digest2 = graph_canonical_digest(example_graph_2)
    if digest1 != digest2 or to_isomorphic(example_graph) != to_isomorphic(example_graph_2):
        validation_errors.append("deterministic rebuild produced a different RDF graph digest")

    if ontology_checksum(ontology_path) != ontology_sha_before:
        validation_errors.append("docs/ontology/eautonome.ttl changed during the run")

    summary = build_summary(
        series_paths=series_paths,
        missing=missing,
        unmapped=unmapped,
        stats_list=stats_list,
        example_graph=example_graph,
        ontology_path=ontology_path,
        ontology_sha_before=ontology_sha_before,
        validation_errors=validation_errors,
        deterministic_hash=digest1,
        source_filenames=source_filenames,
        full_graph_built=full_graph is not None,
    )
    summary["validation_errors"] = validation_errors
    summary["validation_passed"] = len(validation_errors) == 0 and not summary["ontology_schema_changed"]

    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = mapping_run_rows(stats_list, missing)
    with (out / "mapping-run.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({
        "output_dir": str(out),
        "processed_series": [st.series for st in stats_list],
        "missing_documented_series": missing,
        "sensors": summary["sensors_minted"],
        "measurement_points": summary["measurement_points_minted"],
        "source_rows_mapped_as_observations": summary["total_source_rows_mapped_as_observations"],
        "native_consumption_events_mapped": summary["native_consumption_events_mapped"],
        "observation_collections_mapped": summary["observation_collections_mapped"],
        "example_observations_serialized": summary["example_observations_serialized"],
        "example_consumption_events_serialized": summary["example_consumption_events_serialized"],
        "example_observation_collections_serialized": summary["example_observation_collections_serialized"],
        "full_graph_built": summary["full_graph_built"],
        "example_triples": summary["example_graph_triples"],
        "validation_passed": summary["validation_passed"],
        "validation_errors": validation_errors,
    }, indent=2))
    return 0 if summary["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
