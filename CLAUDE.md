# CLAUDE.md

Guidance for a coding agent working in this repository. See `PROJECT.md` for the full project spec, goals, and acceptance criteria — this file is the operating reference: repo conventions, current state, and the NEMSIS domain facts needed to implement this correctly without re-deriving them from scratch.

## Current state

The pipeline runs end to end. On disk and working:

- `reference/xsd/` — 28 EMS component XSDs, pinned to NEMSIS tag `3.5.0.230317CP4` (`VERSION.txt`).
- `reference/samples/ems_xml/` — the 40 official EMS sample PCRs at the *same* tag. All 40 pass every gate.
- `reference/definedlists/` — ICD-10 / RxNorm / SNOMED tables for the fields the XSDs cannot enumerate.
- `reference/valuesets.json` — 467 fields, 214 XSD code tables, 6 defined lists, 2834 codes.
- `nemsis_gen/schema_model.py` — the document's element order, read from the XSDs rather than transcribed.
- `nemsis_gen/render.py` — builds the XML from a value tree; round-trips all 40 samples back to valid.
- `nemsis_gen/generate.py` — two-stage generation (clinical intent, then code selection).
- `nemsis_gen/mutate.py` — the four deterministic corruptions behind the invalid-by-design tiers.
- `nemsis_gen/validate.py` — three gates plus defined-list advisories.
- `nemsis_gen/cli.py` — `generate`, `validate`, `profiles`, `valuesets build|show`.

Verified live against `claude-opus-5`: all seven profiles generated and each matched
its expected validation outcome. Prompt caching confirmed working (85k cache reads,
zero re-creation on the second run of a session).

Not yet done: `--concurrency`, the Schematron gate, and widening the field plan
(sections outside it are inherited from the template, so e.g. `eInjury.01` still
carries the template's cause-of-injury code on a medical call).

## Suggested project layout

```
.
├── CLAUDE.md
├── PROJECT.md
├── pyproject.toml
├── .env.example
├── reference/
│   ├── xsd/                        # full NEMSIS XSD set — root + all 27 includes, siblings
│   ├── sample_valid_v350.xml
│   └── sample_weak_narrative_v350.xml
├── nemsis_gen/
│   ├── __init__.py
│   ├── cli.py                      # entry point
│   ├── api_client.py               # Anthropic call wrapper: retries, backoff, caching
│   ├── profiles.py                 # quality-profile config loading
│   ├── validate.py                 # lxml XSD validation
│   └── prompts/
│       ├── system_base.md          # fixed structural rules block (cacheable)
│       └── profiles.yaml           # per-profile instruction snippets
├── tests/
└── manifest/                       # generation run logs land here (gitignore this)
```

## Tooling & conventions

- Python 3.11+.
- Pick one dependency manager (`uv` recommended) and don't mix in a second.
- Lint/format with `ruff` (and `ruff format`, or `black` if preferred — pick one).
- Type hints on all public functions.
- Tests with `pytest`. Every quality profile should have at least one test asserting its generated output validates — or fails to validate — in the expected way.
- No secrets in the repo. `ANTHROPIC_API_KEY` comes from the environment or `.env` via `python-dotenv`. Add `.env` to `.gitignore` before the first commit; ship `.env.example` with the variable name and no value.

## Commands

`uv` is not installed on the current machine; the venv was bootstrapped with `pip`.
`pyproject.toml` is uv-compatible, so `uv sync` works once it is available.

- Install: `python -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"`
- Generate: `python -m nemsis_gen generate --profile fully_valid --scenario-file scenarios/copd_als.yaml --count 5 --out-dir out/`
- Estimate first: same command with `--dry-run` (no API calls)
- List tiers: `python -m nemsis_gen profiles`
- Validate: `python -m nemsis_gen validate out/`
- Rebuild code tables: `python -m nemsis_gen valuesets build`
- Inspect a field: `python -m nemsis_gen valuesets show eMedications.03`
- Test: `.venv/Scripts/python.exe -m pytest`
- Lint: `.venv/Scripts/python.exe -m ruff check .`

## NEMSIS domain facts

- Standard: NEMSIS v3.5.0. Root element `EMSDataSet`, namespace `http://www.nemsis.org`, referencing `xsi:schemaLocation="http://www.nemsis.org http://nemsis.org/media/nemsis_v3/release-3.5.0/XSDs/NEMSIS_XSDs/EMSDataSet_v3.xsd"`.

- Document shape: `EMSDataSet > Header > (DemographicGroup, PatientCareReport[+])`. `PatientCareReport` carries a required `UUID` attribute, and its children are an `xs:sequence` — a **fixed element order**, not `xs:all`. Getting the order wrong is one of the easiest ways to accidentally produce a false "invalid" record. The order:

  1. `eRecord` — required
    2. `eResponse` — required
      3. `eDispatch` — required
        4. `eCrew` — optional
          5. `eTimes` — required
            6. `ePatient` — required
              7. `ePayment` — required
                8. `eScene` — required
                  9. `eSituation` — required
                    10. `eInjury` — required
                      11. `eArrest` — required
                        12. `eHistory` — required
                          13. `eNarrative` — optional
                            14. `eVitals` — required
                              15. `eLabs` — optional
                                16. `eExam` — optional
                                  17. `eProtocols` — required
                                    18. `eMedications` — required
                                      19. `eProcedures` — required
                                        20. `eAirway` — optional
                                          21. `eDevice` — optional
                                            22. `eDisposition` — required
                                              23. `eOutcome` — required
                                                24. `eCustomResults` — optional
                                                  25. `eOther` — optional

                                                  - The root `EMSDataSet_v3.xsd` (goes in `reference/xsd/`) defines only the envelope and `<xs:include>`s 27 component schemas — one per section above (`eRecord_v3.xsd`, `eResponse_v3.xsd`, ...) plus `commonTypes_v3.xsd`, `dAgency_v3.xsd`, and `eCustom_v3.xsd`. All 27 must be on disk as siblings of the root XSD, with matching filenames, or `lxml.etree.XMLSchema` cannot resolve the includes and validation will fail before it even gets to checking the instance document.

                                                  - NEMSIS fields are heavily coded/enumerated rather than free text — most leaf elements expect a value from a specific national reference value set, not prose. **The value sets do not need to be sourced separately: they are in the XSDs.** Every enumerated field's type is an `xs:simpleType` whose `xs:enumeration` values are the national codes, each annotated with its human-readable label, and the element declarations carry `name`, `definition` and `usage` (Mandatory/Required/Recommended/Optional) in a `nemsisTacDoc` annotation block. `nemsis_gen/valuesets.py` extracts all of it; `nemsis-gen valuesets show eDispatch.01` prints a field's legal values. Codes are 7 digits, first four encoding section+element (`eDispatch.01` -> `2301001`...), which is also what makes the `code_value_violations` profile cheap to synthesise.

  Correction to earlier notes in this file: the codes in the official sample data are **real production value-set codes**, not placeholders — all 10,191 coded values across the 40 sample PCRs verify against the derived tables (`tests/test_reference_baseline.py`). The synthetic-looking values in those files are the free-text and identifier fields (`eResponse.03` = `Ekx`), not the enumerations. `code_value_violations` is therefore not blocked on anything.

  Fields drawing on *external* clinical vocabularies are covered by the NEMSIS **Defined Lists**, not the XSDs: `/DefinedLists/` in the same repo publishes them as JSON/CSV/XLSX, and each file self-describes which elements it governs, so `load_defined_lists()` wires them in without a hardcoded field map. Fetched into `reference/definedlists/`: Impression (ICD-10 -> `eSituation.11`/`.12`, 122 codes), Medication (RxNorm/SNOMED -> `eMedications.03`, 69), Procedure (SNOMED -> `eProcedures.03`, 114), Symptom (`eSituation.09`/`.10`), CauseOfInjury (`eInjury.01`), IncidentLocationType (`eScene.09`). Small enough to inject wholesale into a prompt.

  A defined list is a **curated subset, not a closed enumeration** — the XSD types for these fields admit any well-formed code from the underlying vocabulary, and the official sample corpus sits outside the lists most of the time (e.g. 31/47 `eProcedures.03` values). So membership is reported as an advisory (`defined_list_warnings`), never as a validation failure. The generator should still select from the list; the advisory is how you detect when it didn't.

  `eMedications.03` also carries a required `CodeType` attribute (`9924003` RxNorm, `9924005` SNOMED-CT) that the renderer must emit alongside the code.

- `eNarrative.01` is the free-text narrative field. It's the field the `valid_weak_narrative` profile manipulates: the rest of the record (vitals, exam findings, interventions in `eMedications`/`eProcedures`) stays schema-valid and clinically coherent for the level of care billed, but the narrative itself never establishes medical necessity for ambulance transport under CMS standards (42 CFR 410.40 / Medicare Benefit Policy Manual Ch. 10) — no statement that transport by other means was unsafe, patient described as ambulatory/low-acuity throughout, interventions never tied back to a stated clinical reason. Use this same lever for any other "documentation quality" tier that gets added later.

                                                  - Source of all reference material: `git.nemsis.org`, project `NEP`, repo `nemsis_public` (public, read-only, no auth required to browse). Useful paths:
                                                    - `/XSDs/NEMSIS_EMS_XSDs/` — individual component XSDs, viewable as text in-browser
                                                      - `/SampleData/EMS/xml/` — official sample PCR instances (`ElementsRepeat`, `Nils`, `NoRepeat`, `PNs` series — ten of each, useful as additional structural fixtures beyond the one already pulled)
                                                        - Packaged schema zip, no git browsing needed: `https://nemsis.org/media/nemsis_v3/release-3.5.0/XSDs/NEMSIS_XSDs.zip`

                                                        ## Claude API call pattern

Two calls per record, not one — the split is the design, not an optimisation:

1. **Stage A (clinical).** The model returns a plain-language clinical account as
   JSON. No codes, no XML.
2. **Stage B (encoding).** It gets the same catalogue plus its own stage A output
   and picks a code per field. `temperature=0` — selection is a lookup.

Then `render.py` places the values into the document in schema order. The model
never emits XML, so element-ordering and namespace errors cannot happen by
accident — only deliberately, via `mutate.py`. And it never recalls a code from
memory, which is the failure mode that yields plausible, wrong, hard-to-spot data.

- **Model choice (measured, not assumed).** `claude-sonnet-5` is the floor for
  production use: it holds the rubric gradation apart and keeps value sets straight,
  at roughly half the cost of Opus. `claude-haiku-4-5` cross-contaminated value sets
  (put an `eSituation.13` Initial Acuity code into `eDisposition.19` Final Acuity) and
  flattened initial/final acuity to the same value — the post-hoc registry check
  caught it, but a regeneration loop is then part of the cost. Splitting the stages
  across models (`--coder-model`) is a **false economy**: prompt caches are
  model-scoped, so the ~10k-token catalogue gets created twice and Opus+Haiku measured
  *more* expensive than Opus alone ($0.52 vs $0.38 per 2 records).
- **No `temperature`.** The sampling parameters were removed on Opus 5 and return a
  400. Depth is `output_config: {effort: ...}` instead — profiles set `effort: high`
  for clinical content, and stage B always runs at `effort: low` because selection is
  a lookup, not a creative act. Thinking is on by default on this model, so the
  `thinking` parameter is left unset.
- Server-side refusal fallback (`fallbacks: "default"`) is on by default; if the beta
  is not enabled on the account the client downgrades once and carries on rather than
  failing the run.
- `system` is two blocks: the fixed base prompt concatenated with the ~10k-token
  code catalogue (`cache_control: ephemeral` — byte-identical across a whole run,
  so it is paid for roughly once), then the per-profile narrative block.
- Output contract: JSON only, between `<json>` and `</json>` markers, extracted by
  plain string split. A response without the markers is a logged manifest failure
  (`output_contract_violation`), never a silent skip.
- Every selected code is re-checked against the registry after the fact and
  recorded in `unknown_codes`. The model's claim about its own output is never
  taken at face value.
- Back off and retry on 429/408/5xx; per-call token usage lands in the manifest.

## Things not to do

                                                            - No real patient data anywhere in this repo, at any point. Every fixture and every generated file is synthetic.
                                                            - No hardcoded API keys; no committed `.env`.
                                                            - Don't assume PCR element order is flexible — it's `xs:sequence`, and mis-ordering is one of the easiest accidental ways to produce a false-negative "invalid" result during testing.
                                                            - Don't use `reference/samples/_stale_package/` EMS XML as a fixture — those files predate a schema fix and fail XSD on `ProcedureGroupCorrelationID` (`minLength=2`). Use `reference/samples/ems_xml/`.
- Don't upgrade `reference/xsd/` without re-fetching the samples at the same tag. Upstream's published sample data lags its own schema: at tag `3.5.0.250403CP5` and later, `ePatient.25` became a required element but the shipped samples still omit it, so the official corpus fails the official schema. Pinning both to one tag is what keeps the baseline test meaningful.
