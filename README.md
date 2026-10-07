# The Eautonome Ontology

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22229871.svg)](https://doi.org/10.5281/zenodo.22229871)

The Eautonome Ontology is an OWL ontology for residential water end-use monitoring. It was developed within the Eautonome graywater monitoring system of the OPUR research program at LEESU, ENPC, Institut Polytechnique de Paris.

The ontology reuses SOSA/SSN for the representation of observations and ETSI SAREF4WATR for water terminology. It aligns the two vocabularies at the class level and extends them with concepts for household water use. These concepts cover measurement points, rooms, pipe configurations, and consumption events.

## Persistent identifiers

The ontology is published under the persistent `w3id.org` namespace with HTTP content negotiation.

* Namespace and documentation: https://w3id.org/eautonome/
* Turtle: https://w3id.org/eautonome/eautonome.ttl
* RDF/XML: https://w3id.org/eautonome/eautonome.rdf
* JSON-LD: https://w3id.org/eautonome/eautonome.jsonld
* N-Triples: https://w3id.org/eautonome/eautonome.nt

## Contents

The repository contains:

* The ontology in Turtle, RDF/XML, JSON-LD, and N-Triples
* Two example observation datasets in JSON-LD
* SHACL shapes for data validation (`eautonome-shapes.ttl`)
* Thirteen SPARQL queries used in the ontology evaluation, together with their expected result counts
* Additional analyses provided in the analysis/ directory

## Reused vocabularies

The ontology reuses or references the following vocabularies:

* W3C SOSA/SSN
* ETSI SAREF4WATR
* OWL-Time
* QUDT
* schema.org

## Validation

The ontology is defined in OWL 2 DL and was validated using ROBOT. Its consistency was checked with the HermiT reasoner.

The published ontology and example datasets were validated against seven SHACL shapes and conform to the published SHACL constraints.

The SHACL validation can be reproduced using pySHACL:

```bash
pip install pyshacl
pyshacl -s docs/ontology/eautonome-shapes.ttl \
  docs/ontology/eautonome.ttl \
  docs/data/hydrodynamic-observations.jsonld \
  docs/data/shower-observations.jsonld
```

## Reproducibility

The thirteen SPARQL queries used in the evaluation are provided in the `queries/` directory. Their expected row counts are listed in `expected-results.csv`.

The query evaluation can be reproduced using RDFLib:

```bash
pip install rdflib
python run_queries.py \
  docs/ontology/eautonome.ttl \
  docs/data/hydrodynamic-observations.jsonld \
  docs/data/shower-observations.jsonld
```

The script reports the result count for each query and returns a nonzero exit status if a result differs from the expected value.

### Additional analysis

The `analysis/` directory contains the ablation and sensor coverage analyses.

The analysis can be reproduced from the repository root with:

```bash
python analysis/run_resource_analysis.py \
  docs/ontology/eautonome.ttl \
  docs/data/hydrodynamic-observations.jsonld \
  docs/data/shower-observations.jsonld \
  queries
```

### External reuse checks

HSB Living Lab water data (DOI: https://doi.org/10.5281/zenodo.18971107). 

```bash
python analysis/external-hsb/run_hsb_external_reuse.py \
  /path/to/HSB_Living_Lab_Water_Consumption_Anonymized.csv \
  --output-dir analysis/external-hsb/results
```

WEUSEDTO (DOI: https://doi.org/10.1016/j.softx.2022.101214, CC BY 4.0). 

```bash
python analysis/external-weusedto/run_weusedto_external_reuse.py \
  /path/to/WEUSEDTO/data \
  --output-dir analysis/external-weusedto/results
```

The external sources are not redistributed in this repository.

### LinkML check

`analysis/linkml-compatibility/` tests a composed LinkML schema against SOSA/SSN and SAREF4WATR.

## Citation

Önal, E. (2026). *The Eautonome Ontology* (Version v1.0.1) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22229871

## License

The ontology is released under the Creative Commons Attribution 4.0 International License (CC BY 4.0).

## Contact

Erdem Önal  
LEESU, ENPC, Institut Polytechnique de Paris  
erdem.onal [at] enpc.fr
