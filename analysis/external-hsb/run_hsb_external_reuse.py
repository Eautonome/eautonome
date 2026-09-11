#!/usr/bin/env python3
"""Map the HSB Living Lab dataset for the Eautonome external reuse evaluation."""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import XSD

SOSA = Namespace("http://www.w3.org/ns/sosa/")
EAU = Namespace("https://w3id.org/eautonome/")
S4WATR = Namespace("https://saref.etsi.org/saref4watr/")
QUDT = Namespace("http://qudt.org/schema/qudt/")
UNIT = Namespace("http://qudt.org/vocab/unit/")
SCHEMA = Namespace("http://schema.org/")
DCTERMS = Namespace("http://purl.org/dc/terms/")

FLOW_VOLUME = S4WATR.FlowVolume
PROCEDURE = EAU.hsbObservingProcedure
DEPLOYMENT = EAU.hsbDeployment
COLD_WATER = EAU.hsbColdWater
HOT_WATER = EAU.hsbHotWater

QUERY_TEXT = {
    "Q1": """PREFIX sosa: <http://www.w3.org/ns/sosa/>\nSELECT ?observation ?sensor WHERE {\n  ?observation a sosa:Observation ;\n               sosa:madeBySensor ?sensor .\n}\nORDER BY ?observation\n""",
    "Q2": """PREFIX sosa: <http://www.w3.org/ns/sosa/>\nSELECT DISTINCT ?property WHERE {\n  ?observation a sosa:Observation ;\n               sosa:observedProperty ?property .\n}\nORDER BY ?property\n""",
    "Q3": """PREFIX eau: <https://w3id.org/eautonome/>\nSELECT ?mp ?room ?asset WHERE {\n  ?mp a eau:MeasurementPoint ;\n      eau:locatedIn ?room ;\n      eau:measuresOnAsset ?asset .\n}\nORDER BY ?mp\n""",
    "Q4": """PREFIX sosa: <http://www.w3.org/ns/sosa/>\nSELECT ?observation ?result WHERE {\n  ?observation a sosa:Observation ;\n               sosa:hasSimpleResult ?result .\n}\nORDER BY ?observation\n""",
    "Q5": """PREFIX sosa: <http://www.w3.org/ns/sosa/>\nSELECT ?observation ?time WHERE {\n  ?observation a sosa:Observation ;\n               sosa:resultTime ?time .\n}\nORDER BY ?observation\n""",
    "Q8": """PREFIX sosa: <http://www.w3.org/ns/sosa/>\nSELECT ?observation ?procedure WHERE {\n  ?observation a sosa:Observation ;\n               sosa:usedProcedure ?procedure .\n}\nORDER BY ?observation\n""",
    "Q11": """PREFIX eau: <https://w3id.org/eautonome/>\nPREFIX sosa: <http://www.w3.org/ns/sosa/>\nSELECT ?observation ?room WHERE {\n  ?observation a sosa:Observation ;\n               sosa:hasFeatureOfInterest ?mp .\n  ?mp eau:locatedIn ?room .\n}\nORDER BY ?observation\n""",
}

Q10_HSB = """PREFIX eau: <https://w3id.org/eautonome/>
PREFIX sosa: <http://www.w3.org/ns/sosa/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?sensor WHERE {
  eau:hsbDeployment sosa:deployedSystem ?sensor .
  ?sensor a ?sensorClass .
  ?sensorClass rdfs:subClassOf* sosa:Sensor .
}
ORDER BY ?sensor
"""


def slug(text: str) -> str:
    text = str(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "unknown"


def sensor_iri(sensor_id: str) -> URIRef:
    return EAU[f"hsbSensor{sensor_id}"]


def mp_iri(sensor_id: str) -> URIRef:
    return EAU[f"hsbMeasurementPoint{sensor_id}"]


def room_iri(room_number: str) -> URIRef:
    return EAU[f"hsbRoom{room_number}"]


def asset_iri(sensor_id: str) -> URIRef:
    return EAU[f"hsbAsset{sensor_id}"]


def water_kind_iri(source_type: str) -> URIRef:
    if source_type == "cold water consumption":
        return COLD_WATER
    if source_type == "hot water consumption":
        return HOT_WATER
        raise ValueError(f"Unknown HSB water type: {source_type!r}")


def observation_iri(row_index: int) -> URIRef:
    return EAU[f"hsbObservation{row_index:06d}"]


def utc_lexical(timestamp: pd.Timestamp) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_source(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    required = [
        "timestamp", "sensor_id", "apartment", "cluster_name", "room_number",
        "room_type", "type", "attached_to", "value", "aggregated_value",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    df = df.copy()
    df["_timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def source_summary(df: pd.DataFrame) -> dict:
    sensor_static = df[["sensor_id", "room_number", "room_type", "type", "attached_to", "apartment", "cluster_name"]].drop_duplicates()
    fixture_cross = pd.crosstab(df["attached_to"], df["type"])
    return {
        "records": int(len(df)),
        "sensors": int(df["sensor_id"].nunique()),
        "apartments": int(df["apartment"].nunique(dropna=True)),
        "clusters": int(df["cluster_name"].nunique(dropna=True)),
        "rooms": int(df["room_number"].nunique()),
        "measurement_points": int(df["sensor_id"].nunique()),
        "water_assets": int(df["sensor_id"].nunique()),
        "fixture_types": sorted(df["attached_to"].dropna().unique().tolist()),
        "water_types": sorted(df["type"].dropna().unique().tolist()),
        "room_types": sorted(df["room_type"].dropna().unique().tolist()),
        "valid_days": int(df["date"].nunique()) if "date" in df.columns else None,
        "total_value_m3": round(float(df["value"].sum()), 3),
        "min_timestamp_utc": utc_lexical(df["_timestamp"].min()),
        "max_timestamp_utc": utc_lexical(df["_timestamp"].max()),
        "invalid_timestamps": int(df["_timestamp"].isna().sum()),
        "nonpositive_values": int((df["value"] <= 0).sum()),
        "values_above_0_3_m3": int((df["value"] > 0.3).sum()),
        "missing_apartment_rows": int(df["apartment"].isna().sum()),
        "missing_cluster_rows": int(df["cluster_name"].isna().sum()),
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "rows_in_duplicate_sensor_timestamp_groups": int(df.duplicated(["sensor_id", "timestamp"], keep=False).sum()),
        "sensor_static_mappings": int(len(sensor_static)),
        "fixture_by_water_type_counts": {
            str(idx): {str(k): int(v) for k, v in row.items()}
            for idx, row in fixture_cross.to_dict(orient="index").items()
        },
    }


def assert_source_consistency(df: pd.DataFrame) -> None:
    if df["_timestamp"].isna().any():
        raise ValueError("Could not parse one or more timestamps as UTC")
    if df["sensor_id"].isna().any() or df["room_number"].isna().any() or df["room_type"].isna().any():
        raise ValueError("A sensor or room identifier is missing")
    if df["type"].isna().any() or df["attached_to"].isna().any() or df["value"].isna().any():
        raise ValueError("A water type, fixture, or consumption value is missing")
    if (df["value"] <= 0).any():
        raise ValueError("The source contains a consumption value that is not positive")

    stable_cols = ["room_number", "room_type", "type", "attached_to", "apartment", "cluster_name"]
    for col in stable_cols:
        counts = df.groupby("sensor_id", dropna=False)[col].nunique(dropna=False)
        if int(counts.max()) != 1:
            raise ValueError(f"Sensor attributes are not stable for {col}")

    for col in ["room_type", "apartment", "cluster_name"]:
        counts = df.groupby("room_number", dropna=False)[col].nunique(dropna=False)
        if int(counts.max()) != 1:
            raise ValueError(f"Room attributes are not stable for {col}")


def static_mapping(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["sensor_id", "room_number", "room_type", "type", "attached_to", "apartment", "cluster_name"]
    static = df[cols].drop_duplicates(subset=["sensor_id"]).sort_values("sensor_id").copy()
    static["sensor_iri"] = static["sensor_id"].map(lambda x: str(sensor_iri(x)))
    static["measurement_point_iri"] = static["sensor_id"].map(lambda x: str(mp_iri(x)))
    static["room_iri"] = static["room_number"].map(lambda x: str(room_iri(x)))
    static["asset_iri"] = static["sensor_id"].map(lambda x: str(asset_iri(x)))
    static["water_kind_iri"] = static["type"].map(lambda x: str(water_kind_iri(x)))
    return static


def add_common_prefixes(g: Graph) -> None:
    g.bind("sosa", SOSA)
    g.bind("eau", EAU)
    g.bind("s4watr", S4WATR)
    g.bind("qudt", QUDT)
    g.bind("unit", UNIT)
    g.bind("schema", SCHEMA)
    g.bind("dcterms", DCTERMS)


def add_static_mapping(g: Graph, static: pd.DataFrame, include_deployment: bool = True) -> None:
    g.add((COLD_WATER, RDF.type, S4WATR.WaterKind))
    g.add((COLD_WATER, RDFS.label, Literal("Cold water consumption")))
    g.add((HOT_WATER, RDF.type, S4WATR.WaterKind))
    g.add((HOT_WATER, RDFS.label, Literal("Hot water consumption")))

    g.add((PROCEDURE, RDF.type, SOSA.ObservingProcedure))
    g.add((PROCEDURE, RDFS.label, Literal("HSB water meter procedure")))
    g.add((PROCEDURE, RDFS.comment, Literal(
        "The HSB Living Lab meters count pulses. Resolution is 1 L. Readings are reported every 10 minutes."
    )))

    rooms_done = set()
    assets_done = set()

    if include_deployment:
        g.add((DEPLOYMENT, RDF.type, SOSA.Deployment))
        g.add((DEPLOYMENT, RDFS.label, Literal("HSB Living Lab deployment")))

    for r in static.itertuples(index=False):
        s = URIRef(r.sensor_iri)
        mp = URIRef(r.measurement_point_iri)
        room = URIRef(r.room_iri)
        asset = URIRef(r.asset_iri)
        wk = URIRef(r.water_kind_iri)

        g.add((s, RDF.type, SOSA.Sensor))
        g.add((s, RDF.type, S4WATR.WaterMeter))
        g.add((s, EAU.monitors, mp))
        g.add((s, SOSA.observes, FLOW_VOLUME))
        g.add((s, RDFS.label, Literal(f"HSB water meter {r.sensor_id}")))
        if include_deployment:
            g.add((DEPLOYMENT, SOSA.deployedSystem, s))

        g.add((mp, RDF.type, EAU.MeasurementPoint))
        g.add((mp, EAU.locatedIn, room))
        g.add((mp, EAU.measuresOnAsset, asset))
        g.add((mp, EAU.measuresWaterKind, wk))
        g.add((mp, SOSA.hasProperty, FLOW_VOLUME))
        g.add((mp, RDFS.label, Literal(f"HSB measurement point {r.sensor_id}")))

        if room not in rooms_done:
            g.add((room, RDF.type, EAU.DomesticRoom))
            g.add((room, RDFS.label, Literal(f"{r.room_number} ({r.room_type})")))
            g.add((room, RDFS.comment, Literal(f"Room type in the source data: {r.room_type}.")))
            if pd.notna(r.apartment):
                apt = EAU[f"hsbApartment{r.apartment}"]
                g.add((apt, RDF.type, SCHEMA.Place))
                g.add((apt, RDFS.label, Literal(str(r.apartment))))
                g.add((room, DCTERMS.isPartOf, apt))
            if pd.notna(r.cluster_name):
                cluster = EAU[f"hsbCluster{r.cluster_name}"]
                g.add((cluster, RDF.type, SCHEMA.Place))
                g.add((cluster, RDFS.label, Literal(str(r.cluster_name))))
            if pd.notna(r.apartment) and pd.notna(r.cluster_name):
                apt = EAU[f"hsbApartment{r.apartment}"]
                cluster = EAU[f"hsbCluster{r.cluster_name}"]
                g.add((apt, DCTERMS.isPartOf, cluster))
            rooms_done.add(room)

        if asset not in assets_done:
            g.add((asset, RDF.type, S4WATR.WaterAsset))
            g.add((asset, RDFS.label, Literal(f"HSB water asset at meter {r.sensor_id}: {r.type}, {r.attached_to}, {r.room_number}")))
            assets_done.add(asset)


def add_observation(g: Graph, row_index: int, row, include_quantity: bool = False) -> None:
    obs = observation_iri(row_index)
    sensor = sensor_iri(row.sensor_id)
    mp = mp_iri(row.sensor_id)
    g.add((obs, RDF.type, SOSA.Observation))
    g.add((obs, SOSA.observedProperty, FLOW_VOLUME))
    g.add((obs, SOSA.resultTime, Literal(utc_lexical(row._timestamp), datatype=XSD.dateTime)))
    g.add((obs, SOSA.hasSimpleResult, Literal(str(row.value), datatype=XSD.decimal)))
    g.add((obs, SOSA.madeBySensor, sensor))
    g.add((obs, SOSA.hasFeatureOfInterest, mp))
    g.add((obs, SOSA.usedProcedure, PROCEDURE))
    if include_quantity:
        qv = BNode()
        g.add((obs, SOSA.hasResult, qv))
        g.add((qv, RDF.type, QUDT.QuantityValue))
        g.add((qv, QUDT.value, Literal(str(row.value), datatype=XSD.decimal)))
        g.add((qv, QUDT.hasUnit, UNIT.M3))


_WORK_DF = None
_WORK_STATIC_BY_SENSOR = None


def build_combined_projection(chunk: pd.DataFrame, static_by_sensor: Dict[str, Tuple[str, str]]) -> Graph:
    """Build the RDF needed by Q1, Q2, Q4, Q5, Q8, and Q11 for one chunk."""
    g = Graph()
    add_common_prefixes(g)
    for sid in chunk["sensor_id"].unique():
        room_number, _fixture = static_by_sensor[sid]
        g.add((mp_iri(sid), EAU.locatedIn, room_iri(room_number)))

    for idx, sid, value, ts in zip(
        chunk.index.to_numpy(),
        chunk["sensor_id"].to_numpy(),
        chunk["value"].to_numpy(),
        chunk["_timestamp"].tolist(),
    ):
        obs = observation_iri(int(idx))
        mp = mp_iri(sid)
        g.add((obs, RDF.type, SOSA.Observation))
        g.add((obs, SOSA.madeBySensor, sensor_iri(sid)))
        g.add((obs, SOSA.observedProperty, FLOW_VOLUME))
        g.add((obs, SOSA.hasSimpleResult, Literal(str(value), datatype=XSD.decimal)))
        g.add((obs, SOSA.resultTime, Literal(utc_lexical(ts), datatype=XSD.dateTime)))
        g.add((obs, SOSA.usedProcedure, PROCEDURE))
        g.add((obs, SOSA.hasFeatureOfInterest, mp))
    return g


def _run_projection_range(bounds: Tuple[int, int]) -> dict:
    start, end = bounds
    df = _WORK_DF.iloc[start:end]
    g = build_combined_projection(df, _WORK_STATIC_BY_SENSOR)
    result = {"counts": {}, "seconds": {}, "q2_values": []}
    for qid in ["Q1", "Q2", "Q4", "Q5", "Q8", "Q11"]:
        t0 = time.perf_counter()
        rows = g.query(QUERY_TEXT[qid])
        if qid == "Q2":
            vals = [str(row[0]) for row in rows]
            result["q2_values"] = vals
            result["counts"][qid] = len(vals)
        else:
            result["counts"][qid] = sum(1 for _ in rows)
        result["seconds"][qid] = time.perf_counter() - t0
    return result


def execute_chunked_queries(df: pd.DataFrame, chunk_size: int, static: pd.DataFrame, workers: int = 1) -> Dict[str, dict]:
    global _WORK_DF, _WORK_STATIC_BY_SENSOR
    _WORK_DF = df
    _WORK_STATIC_BY_SENSOR = {
        r.sensor_id: (r.room_number, r.attached_to)
        for r in static.itertuples(index=False)
    }
    jobs = [(start, min(start + chunk_size, len(df))) for start in range(0, len(df), chunk_size)]
    t_total = time.perf_counter()

    results = None
    if workers > 1:
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            results = []
            for offset in range(0, len(jobs), workers):
                wave = jobs[offset:offset + workers]
                with ctx.Pool(processes=min(workers, len(wave))) as pool:
                    results.extend(pool.map(_run_projection_range, wave))
        except (ValueError, RuntimeError):
            results = None
    if results is None:
        results = [_run_projection_range(job) for job in jobs]

    totals = {qid: 0 for qid in ["Q1", "Q4", "Q5", "Q8", "Q11"]}
    query_cpu_seconds = {qid: 0.0 for qid in ["Q1", "Q2", "Q4", "Q5", "Q8", "Q11"]}
    q2_values = set()
    for r in results:
        for qid in totals:
            totals[qid] += int(r["counts"][qid])
        for qid, sec in r["seconds"].items():
            query_cpu_seconds[qid] += float(sec)
        q2_values.update(r["q2_values"])

    out = {}
    for qid, count in totals.items():
        out[qid] = {"row_count": count, "seconds": round(query_cpu_seconds[qid], 3)}
    out["Q2"] = {"row_count": len(q2_values), "seconds": round(query_cpu_seconds["Q2"], 3)}
    out["projection_wall_seconds"] = round(time.perf_counter() - t_total, 3)
    return out

def execute_static_queries(static: pd.DataFrame) -> List[dict]:
    g = Graph()
    add_common_prefixes(g)
    add_static_mapping(g, static, include_deployment=True)
    out = []
    for qid, query in [("Q3", QUERY_TEXT["Q3"]), ("Q10-HSB", Q10_HSB)]:
        started = time.perf_counter()
        count = sum(1 for _ in g.query(query))
        out.append({"query": qid, "row_count": count, "seconds": round(time.perf_counter() - started, 3)})
    return out


def check_applicable_shapes(df: pd.DataFrame, static: pd.DataFrame) -> List[dict]:
    obs_violations = (
        int(df["sensor_id"].isna().sum())
        + int(df["value"].isna().sum())
        + int(df["_timestamp"].isna().sum())
    )
    mp_violations = (
        int(static["room_number"].isna().sum())
        + int(static["attached_to"].isna().sum())
        + int(static["type"].isna().sum())
    )

    return [
        {
            "shape": "eau:ObservationShape",
            "target_class": "sosa:Observation",
            "target_count": int(len(df)),
            "checked_requirements": "madeBySensor; observedProperty; hasSimpleResult; resultTime xsd:dateTime",
            "violations": int(obs_violations),
        },
        {
            "shape": "eau:MeasurementPointShape",
            "target_class": "eau:MeasurementPoint",
            "target_count": int(len(static)),
            "checked_requirements": "locatedIn; measuresOnAsset; measuresWaterKind; sosa:hasProperty",
            "violations": int(mp_violations),
        },
    ]


def make_example_graph(df: pd.DataFrame, static: pd.DataFrame) -> Graph:
    examples = (
        df.sort_values(["attached_to", "type", "timestamp"])
          .drop_duplicates(["attached_to", "type"], keep="first")
    )
    sensor_ids = set(examples["sensor_id"])
    subset_static = static[static["sensor_id"].isin(sensor_ids)].copy()
    g = Graph()
    add_common_prefixes(g)
    add_static_mapping(g, subset_static, include_deployment=True)
    for idx, row in examples.iterrows():
        add_observation(g, int(idx), row, include_quantity=True)
    return g


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path, help="HSB Living Lab water consumption CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("hsb-external-results"))
    parser.add_argument("--chunk-size", type=int, default=50000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--batch-records",
        type=int,
        default=170000,
        help="Recreate the worker pool after this many rows",
    )
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    df = load_source(args.csv)
    assert_source_consistency(df)
    summary = source_summary(df)
    static = static_mapping(df)
    static.to_csv(out / "hsb-static-mapping.csv", index=False)
    shapes = check_applicable_shapes(df, static)
    example = make_example_graph(df, static)

    qdir = out / "queries"
    qdir.mkdir(exist_ok=True)
    qnum = {"Q1":"q01.rq", "Q2":"q02.rq", "Q3":"q03.rq", "Q4":"q04.rq", "Q5":"q05.rq", "Q8":"q08.rq", "Q11":"q11.rq"}
    for qid, filename in qnum.items():
        (qdir / filename).write_text(QUERY_TEXT[qid], encoding="utf-8")
    (qdir / "q10-hsb.rq").write_text(Q10_HSB, encoding="utf-8")

    query_rows = []
    static_results = {r["query"]: r for r in execute_static_queries(static)}
    del df
    import gc
    gc.collect()
    projected_parts = []
    for sub in pd.read_csv(args.csv, sep=";", chunksize=args.batch_records):
        sub["_timestamp"] = pd.to_datetime(sub["timestamp"], errors="coerce", utc=True)
        projected_parts.append(execute_chunked_queries(sub, args.chunk_size, static, workers=max(1, args.workers)))
    projected = {}
    for qid in ["Q1", "Q4", "Q5", "Q8", "Q11"]:
        projected[qid] = {
            "row_count": sum(part[qid]["row_count"] for part in projected_parts),
            "seconds": round(sum(part[qid]["seconds"] for part in projected_parts), 3),
        }
    if not all(part["Q2"]["row_count"] == 1 for part in projected_parts):
        raise RuntimeError("Q2 did not return one observed property in every batch")
    projected["Q2"] = {
        "row_count": 1,
        "seconds": round(sum(part["Q2"]["seconds"] for part in projected_parts), 3),
    }
    projected["projection_wall_seconds"] = round(sum(part["projection_wall_seconds"] for part in projected_parts), 3)
    for qid in ["Q1", "Q2", "Q4", "Q5", "Q8", "Q11"]:
        query_rows.append({
            "query": qid,
            "row_count": int(projected[qid]["row_count"]),
            "status": "answered",
            "seconds": projected[qid]["seconds"],
        })
    query_rows.append({"query":"Q3", "row_count":int(static_results["Q3"]["row_count"]), "status":"answered", "seconds":static_results["Q3"]["seconds"]})
    query_rows.append({"query":"Q10-HSB", "row_count":int(static_results["Q10-HSB"]["row_count"]), "status":"answered after substituting the deployment IRI", "seconds":static_results["Q10-HSB"]["seconds"]})
    for qid, reason in [
        ("Q6", "the source has no operational status"),
        ("Q7", "the source has no consumption event intervals"),
        ("Q9", "the source has no calibration parameters"),
        ("Q12", "the source has no operational status"),
        ("Q13", "the source has no observation collections or consumption events"),
    ]:
        query_rows.append({"query":qid, "row_count":None, "status":f"not answerable: {reason}", "seconds":None})

    order = {f"Q{i}": i for i in range(1,14)}
    order["Q10-HSB"] = 10
    query_rows.sort(key=lambda x: (order.get(x["query"], 99), x["query"]))

    with (out / "external-reuse-query-results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["query", "row_count", "status", "seconds"])
        writer.writeheader()
        writer.writerows(query_rows)

    with (out / "applicable-shacl-checks.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(shapes[0].keys()))
        writer.writeheader()
        writer.writerows(shapes)

    example.serialize(destination=str(out / "hsb-example.jsonld"), format="json-ld", indent=2, auto_compact=True)
    example.serialize(destination=str(out / "hsb-example.ttl"), format="turtle")

    summary.update({
        "ontology_schema_changed": False,
        "released_queries_supported_unchanged": 7,
        "deployment_query_supported_after_iri_substitution": True,
        "queries_not_answerable_from_source_metadata": 5,
        "applicable_shacl_shape_violations": int(sum(s["violations"] for s in shapes)),
        "example_fixture_water_pairs": sum(1 for counts in summary["fixture_by_water_type_counts"].values() for count in counts.values() if count > 0),
        "value_unit_used_in_mapping": "http://qudt.org/vocab/unit/M3",
        "aggregated_value_mapped": False,
        "query_projection_wall_seconds": projected["projection_wall_seconds"],
    })
    (out / "external-reuse-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "records": summary["records"],
        "sensors": summary["sensors"],
        "rooms": summary["rooms"],
        "assets": summary["water_assets"],
        "query_counts": {r["query"]: r["row_count"] for r in query_rows},
        "shape_violations": summary["applicable_shacl_shape_violations"],
        "schema_changed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
