# CLAUDE.md

Guidance for a coding agent working in this repository. See `PROJECT.md` for the full project spec, goals, and acceptance criteria — this file is the operating reference: repo conventions, current state, and the NEMSIS domain facts needed to implement this correctly without re-deriving them from scratch.

## Current state

Phase 0 and Phase 1 are done. On disk and working:

- `reference/xsd/` — all 28 EMS component XSDs, pinned to NEMSIS tag `3.5.0.230317CP4` (`VERSION.txt`).
- `reference/samples/ems_xml/` — the 40 official EMS sample PCRs at the *same* tag. All 40 pass every gate.
- `reference/valuesets.json` — 467 field definitions and 214 code tables (2350 codes) derived from the XSDs by `nemsis_gen/valuesets.py`.
- `nemsis_gen/validate.py` — three independent gates: well-formedness, XSD, value-set legality.
- `nemsis_gen/cli.py` — `valuesets build|show` and `validate`.

Next: the two-stage generator (clinical intermediate -> code selection -> code-side XML rendering),
the graduated 1-5 narrative-quality rubric, and the profile mutations.

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
- Rebuild code tables: `python -m nemsis_gen valuesets build`
- Inspect a field: `python -m nemsis_gen valuesets show eDispatch.01`
- Validate: `python -m nemsis_gen validate reference/samples/ems_xml`
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

  Three fields point at *external* terminologies with no enumeration in the XSD and so cannot be reverse-looked-up from the registry: `eSituation.09`/`.10`/`.11`/`.12` (ICD-10), `eMedications.03` (RxNorm), `eProcedures.03` (SNOMED). These need either an external table or model-generated codes flagged as unverified in the manifest.

- `eNarrative.01` is the free-text narrative field. It's the field the `valid_weak_narrative` profile manipulates: the rest of the record (vitals, exam findings, interventions in `eMedications`/`eProcedures`) stays schema-valid and clinically coherent for the level of care billed, but the narrative itself never establishes medical necessity for ambulance transport under CMS standards (42 CFR 410.40 / Medicare Benefit Policy Manual Ch. 10) — no statement that transport by other means was unsafe, patient described as ambulatory/low-acuity throughout, interventions never tied back to a stated clinical reason. Use this same lever for any other "documentation quality" tier that gets added later.

                                                  - Source of all reference material: `git.nemsis.org`, project `NEP`, repo `nemsis_public` (public, read-only, no auth required to browse). Useful paths:
                                                    - `/XSDs/NEMSIS_EMS_XSDs/` — individual component XSDs, viewable as text in-browser
                                                      - `/SampleData/EMS/xml/` — official sample PCR instances (`ElementsRepeat`, `Nils`, `NoRepeat`, `PNs` series — ten of each, useful as additional structural fixtures beyond the one already pulled)
                                                        - Packaged schema zip, no git browsing needed: `https://nemsis.org/media/nemsis_v3/release-3.5.0/XSDs/NEMSIS_XSDs.zip`

                                                        ## Claude API call pattern

                                                        - One `messages.create()` call per generated file to start. Revisit the Batches API once volume and tier mix are known (see "Open questions" in `PROJECT.md`) — not needed for the first version.

                                                        - `system` param, two concatenated blocks:
                                                          1. **Fixed structural block** (`prompts/system_base.md`): the element-order rule above, the namespace/`schemaLocation` requirement, and the hard output-format constraint — *"output ONLY the XML document, no prose, no markdown code fences, wrapped between `<xml>` and `</xml>` markers"* — so the CLI can extract it with a plain string split instead of a fragile regex or markdown-fence guess. Mark this block with `cache_control: {"type": "ephemeral"}`: it's byte-identical on every call within a batch run, so prompt caching meaningfully cuts cost at volume.
                                                            2. **Profile block** (from `prompts/profiles.yaml`, keyed by `--profile`): the specific instruction for this quality tier. For `valid_weak_narrative`, for example: *"the record must be schema-valid and clinically coherent with ALS-level interventions performed, but `eNarrative.01` must NOT establish medical necessity per CMS ambulance-transport standards — do not state that transport by other means was contraindicated, describe the patient as ambulatory and low-acuity, and do not tie the interventions performed back to a stated clinical justification."*

                                                            - `messages`: a single user message containing the template XML (from `--template`, defaulting to `reference/sample_valid_v350.xml`) plus the `--scenario` text (the clinical picture in plain English) plus a restated reminder of the output-format contract.

                                                            - After the response: extract the content between the `<xml>`/`</xml>` markers, write to `out-dir/<profile>_<index>.xml`, run `validate.py` against `reference/xsd/EMSDataSet_v3.xsd`, and append a manifest row with the result. A response that doesn't contain the markers at all is a logged failure, not a silent skip.

                                                            - Error handling: back off and retry on 429s; capture per-call token usage from the API response for the manifest's cost tracking.

                                                            ## Things not to do

                                                            - No real patient data anywhere in this repo, at any point. Every fixture and every generated file is synthetic.
                                                            - No hardcoded API keys; no committed `.env`.
                                                            - Don't assume PCR element order is flexible — it's `xs:sequence`, and mis-ordering is one of the easiest accidental ways to produce a false-negative "invalid" result during testing.
                                                            - Don't use `reference/samples/_stale_package/` EMS XML as a fixture — those files predate a schema fix and fail XSD on `ProcedureGroupCorrelationID` (`minLength=2`). Use `reference/samples/ems_xml/`.
- Don't upgrade `reference/xsd/` without re-fetching the samples at the same tag. Upstream's published sample data lags its own schema: at tag `3.5.0.250403CP5` and later, `ePatient.25` became a required element but the shipped samples still omit it, so the official corpus fails the official schema. Pinning both to one tag is what keeps the baseline test meaningful.
