# NEMSIS Synthetic PCR Generator

## Purpose

A Python CLI tool that uses the Claude API to bulk-generate synthetic NEMSIS v3.5.0 Patient Care Report (PCR) XML files spanning a deliberate range of data-quality tiers, for exercising a downstream NEMSIS XML validation pipeline. Every record is fully synthetic — no real PHI, ever.

## Background

NEMSIS (National EMS Information System) v3.5.0 defines an XML schema for EMS patient care reports. Testing a validator against that schema well requires more than a handful of hand-written fixtures: it needs volume, and it needs deliberate variety — records that are fully compliant, records that are structurally invalid, and records that are schema-valid but fail on softer grounds (like documentation that won't survive a payer's medical-necessity review). This project builds the generator for that fixture set.

Reference material already gathered this session (ship these in `reference/` — see "Suggested layout" in `CLAUDE.md`):

- `EMSDataSet_v3.xsd` — the NEMSIS v3.5.0 root schema, fetched from the official `nemsis_public` git repository (`git.nemsis.org`, project `NEP`).
- `sample_valid_v350.xml` — an official NEMSIS sample PCR instance from the same repo (`SampleData/EMS/xml/`), confirmed well-formed.
- `sample_weak_narrative_v350.xml` — a hand-built worked example: adult male, shortness-of-breath chief complaint, ALS-level care rendered (IV, cardiac monitoring, nebulized albuterol), but the `eNarrative.01` free-text narrative is deliberately written so it does **not** establish medical necessity for ambulance transport under CMS standards (42 CFR 410.40 / Medicare Benefit Policy Manual Ch. 10) — patient documented as ambulatory and low-acuity throughout, no statement that transport by other means was unsafe, interventions never tied back to a stated clinical justification. This is the reference pattern for the `valid_weak_narrative` quality tier below.

## Goals

- A CLI command that takes a quality profile, a clinical scenario description, and a count, and produces N XML files matching that profile.
- Each generation call sends the model: (a) a system prompt encoding the NEMSIS structural rules plus the requested quality profile's specific failure mode (or lack thereof), (b) a template XML as a structural reference, and (c) the scenario description.
- A post-generation validation step that checks each output file against the local NEMSIS XSDs with `lxml`, independent of what the model claims about itself.
- A manifest (JSONL or CSV) logging, per file: filename, quality profile, scenario text, model used, token usage, schema-valid true/false, validation errors if any, timestamp.

## Non-goals (for the first version)

- Maintaining the full NEMSIS code-list / value-set tables (which codes are legal for which enumerated field) is out of scope for the first cut — see "Known gap" below. The two shipped reference samples use placeholder-style codes for structural fields, not verified production values.
- Implementing NEMSIS's Schematron business-rule layer (a stricter check beyond XSD structural validity) — flagged as a possible follow-on, not required initially.
- A GUI or web interface. CLI only.

## Quality tiers to support

The tool should treat "quality profile" as a config-driven string, not a hardcoded enum, so tiers can be added later without a code change. Tiers to seed the config with:

1. **fully_valid** — schema-valid, clinically coherent, and the narrative affirmatively supports medical necessity for the level of transport billed.
2. **valid_weak_narrative** — schema-valid, ALS/BLS-level care documented and billed, but the narrative fails CMS medical-necessity documentation standards. Pattern: `sample_weak_narrative_v350.xml`.
3. **schema_invalid_structural** — deliberately wrong element order, or a required section omitted entirely, or a namespace/schemaLocation error, to exercise the validator's rejection path.
4. **missing_mandatory_fields** — structurally correct, but required leaf elements are empty or absent.
5. **malformed_xml** — broken XML syntax (unescaped ampersands, unclosed tags) to test parser-level failure, not just schema-level failure.
6. **code_value_violations** — structurally valid but using codes outside the legal NEMSIS value set for one or more enumerated fields. (Depends on sourcing the real value-set tables — see "Known gap.")

## CLI design

```
nemsis-gen generate \
  --profile <name> \
    --scenario "<free-text clinical scenario>" \
      --count N \
        --out-dir DIR \
          [--model NAME] \
            [--system-prompt PATH] \
              [--template PATH] \
                [--validate / --no-validate] \
                  [--concurrency N]
                  ```

                  - Quality-profile definitions (description + the profile-specific instruction block to inject into the system prompt) live in a config file, not in code.
                  - `ANTHROPIC_API_KEY` comes from the environment / a `.env` file via `python-dotenv`. Never hardcoded, never committed. Confirm `.env` is in `.gitignore` before the first commit.

                  ## Claude API call shape

                  - Anthropic Python SDK, `client.messages.create()`.
                  - `system`: two concatenated blocks.
                    1. A **fixed structural block** — the NEMSIS element-order rule, namespace/schemaLocation requirement, and the output-format contract ("return only the XML document, wrapped between `<xml>` and `</xml>` markers, no prose, no markdown fences"). This block is identical across every call in a batch run, so mark it for prompt caching — meaningful cost savings at volume.
                      2. A **profile-specific block** — the quality tier's particular instruction, pulled from the profile config.
                      - `messages`: one user message containing the template XML (structural reference) plus the scenario text plus a restated reminder of the output-format contract.
                      - After the response comes back: extract the content between the `<xml>`/`</xml>` markers (a plain string split, not a regex/markdown-fence guess), write it to disk, run local XSD validation, and log a manifest row — including the case where the model didn't follow the format contract at all, which should be recorded as a failure, not silently skipped.

                      See `CLAUDE.md` for the exact NEMSIS structural facts (element order, required vs. optional sections, source URLs) the implementer needs, and for suggested repo layout and conventions.

                      ## Known gap

                      Only the root `EMSDataSet_v3.xsd` has been fetched so far. It `<xs:include>`s 27 component schemas (`commonTypes_v3.xsd`, `ePatient_v3.xsd`, `eVitals_v3.xsd`, etc.) that are **not yet in this repo** — without them, `lxml` cannot resolve the includes and cannot actually validate anything. Fetching the full set (from `git.nemsis.org/projects/NEP/repos/nemsis_public/browse/XSDs/NEMSIS_EMS_XSDs/`, or the packaged zip at `https://nemsis.org/media/nemsis_v3/release-3.5.0/XSDs/NEMSIS_XSDs.zip`) into `reference/xsd/` is the first implementation task, before any validation logic is written.

                      ## Acceptance criteria

                      - `nemsis-gen generate --profile fully_valid --scenario "..." --count 5 --out-dir out/` produces 5 well-formed XML files that pass local XSD validation.
                      - Running an invalid-by-design profile produces files that fail validation in the specific, documented way — and the manifest records *why*, not just pass/fail.
                      - The manifest gives an accurate per-file token/cost figure, so a bulk run's cost can be estimated before committing to a large count.

                      ## Open questions for whoever picks this up

                      - Which model to standardize on, and at what temperature per tier (structural tiers likely want low temperature; narrative variety within a valid tier can tolerate more).
                      - Whether output should also be checked against NEMSIS's own Schematron business-rule set, in addition to XSD structural validity.
                      - Target volume and tier mix for the first real bulk run — this determines whether per-call `messages.create()` is fine or the Batches API is worth the extra plumbing.
