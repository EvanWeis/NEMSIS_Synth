# Reference sample data

## `ems_xml/` — canonical

The 40 official EMS PatientCareReport instances, fetched from `git.nemsis.org`
(project NEP, repo `nemsis_public`) at tag **3.5.0.230317CP4** — the same tag the
XSDs in `reference/xsd/` are pinned to (see `reference/xsd/VERSION.txt`).

All 40 pass well-formedness, XSD, and value-set validation. `tests/` asserts this
on every run; if it ever breaks, the schema set and the corpus have drifted and no
validation verdict on a *generated* file can be trusted.

## `_stale_package/` — do not use as a fixture

The two sample packages originally dropped in the repo root (`NEMSIS_3.5.0_Sample`
and `NEMSIS_3.5.1_Sample`). They were byte-identical to each other despite the
version labels, and their EMS instances fail the 3.5.0 XSD: every
`ProcedureGroupCorrelationID` is one character, but `commonTypes_v3.xsd` has always
imposed `minLength=2` on `CorrelationID`. Upstream fixed this in the regenerated
samples now in `ems_xml/`.

Kept only for `Schematron/`, `DEM/`, `State/` and `CustomElements/`, which have no
pinned equivalent fetched yet. Treat the EMS XML in here as version-skewed.
