"""nemsis-gen command line entry point."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

from .api_client import DEFAULT_MODEL, ApiClient, OutputContractError
from .direct import generate_direct, load_exemplars
from .generate import DEFAULT_TEMPLATE, build_cached_system, generate_record
from .manifest import Manifest
from .mutate import apply_mutation
from .profiles import load_profiles, load_system_base
from .scenario import Scenario
from .validate import DEFAULT_SCHEMA, schematron_validate, validate_file
from .valuesets import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_XSD_DIR,
    build_registry,
    load_registry,
    write_registry,
)

NL = chr(10)


@click.group()
def cli() -> None:
    """Generate and validate synthetic NEMSIS v3.5.0 patient care reports."""


@cli.group()
def valuesets() -> None:
    """Build and query the XSD-derived code tables."""


@valuesets.command("build")
@click.option("--xsd-dir", type=click.Path(path_type=Path), default=DEFAULT_XSD_DIR)
@click.option("--out", type=click.Path(path_type=Path), default=DEFAULT_REGISTRY_PATH)
@click.option("--version", default="3.5.0")
def valuesets_build(xsd_dir: Path, out: Path, version: str) -> None:
    """Re-derive reference/valuesets.json from the XSDs on disk."""
    registry = build_registry(xsd_dir, version=version)
    write_registry(registry, out)
    click.echo(
        f"{len(registry.fields)} fields, {len(registry.types)} value sets, "
        f"{len(registry.all_codes())} codes -> {out}"
    )


@valuesets.command("show")
@click.argument("field")
def valuesets_show(field: str) -> None:
    """Print the legal coded values for a field, e.g. eDispatch.01."""
    registry = load_registry()
    fd = registry.fields.get(field)
    if fd is None:
        raise click.ClickException(f"unknown field {field!r}")
    click.echo(f"{fd.number}  {fd.name}  [{fd.usage}]  type={fd.type_name}")
    if fd.definition:
        click.echo(f"  {fd.definition}")
    if fd.defined_list:
        dl = registry.defined_lists[fd.defined_list]
        click.echo(
            f"  defined list: {dl.name} ({', '.join(dl.source_vocabularies)}) - "
            "a curated subset; the schema admits any valid code from the vocabulary"
        )
    for value in registry.values_for(field):
        suffix = f"  [{value.category}]" if value.category else ""
        click.echo(f"  {value.code}  {value.label}{suffix}")


@cli.command("validate")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--schema", type=click.Path(path_type=Path), default=DEFAULT_SCHEMA)
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON object per file.")
@click.option(
    "--schematron",
    is_flag=True,
    help="Also run Schematron business rules.",
)
@click.option(
    "--rules",
    "rules_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to your own .sch rule set (implies --schematron).",
)
def validate_cmd(
    paths: tuple[Path, ...],
    schema: Path,
    as_json: bool,
    schematron: bool,
    rules_path: Path | None,
) -> None:
    """Validate XML files: well-formedness, XSD structure, and code value sets."""
    registry = load_registry()
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob("*.xml")) if path.is_dir() else [path])

    failed = 0
    for path in files:
        result = validate_file(path, schema_path=schema, registry=registry)
        failed += not result.ok
        sch = None
        if schematron or rules_path is not None:
            sch = schematron_validate(path, rules_path)
        if as_json:
            payload = {"file": str(path), **result.to_json()}
            if sch is not None:
                payload["schematron"] = sch.to_json()
            click.echo(json.dumps(payload))
        else:
            status = "PASS" if result.ok else "FAIL"
            warned = (
                f"  ({len(result.defined_list_warnings)} defined-list advisories)"
                if result.defined_list_warnings
                else ""
            )
            click.echo(f"{status}  {path.name}{warned}")
            for msg in (result.errors + result.code_errors)[:5]:
                click.echo(f"      {msg}")
            if sch is not None:
                if not sch.ran:
                    click.echo(f"      schematron did not run: {sch.error[:90]}")
                else:
                    label = "clean" if sch.ok else f"{len(sch.errors)} error(s)"
                    extra = len(sch.failures) - len(sch.errors)
                    warn = f", {extra} warning(s)" if extra else ""
                    click.echo(f"      schematron [{sch.rules}]: {label}{warn}")
                    for a in sch.errors[:3]:
                        click.echo(f"        {a.rule_id}: {a.message[:88]}")

    if not as_json:
        click.echo(f"\n{len(files) - failed}/{len(files)} passed")
    if failed:
        raise SystemExit(1)


@cli.command("profiles")
def profiles_cmd() -> None:
    """List the configured quality profiles."""
    config = load_profiles()
    for family, profiles in sorted(config.by_family().items()):
        click.echo(NL + family)
        for profile in sorted(profiles, key=lambda p: p.name):
            gate = "ingestible" if profile.ingestible else "rejected at ingest"
            click.echo(f"  {profile.name:26} narrative={profile.narrative_quality}/5  {gate}")
            click.echo(f"    {profile.description}")
            if profile.expected_findings:
                click.echo(f"    expects: {', '.join(profile.expected_findings)}")


@cli.command("generate")
@click.option("--profile", "profile_name", required=True)
@click.option("--scenario", "scenario_text", default=None, help="Free-text clinical scenario.")
@click.option(
    "--scenario-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Structured scenario YAML (patient, scene, assessment, interventions, narrative).",
)
@click.option("--count", default=1, show_default=True)
@click.option(
    "--concurrency",
    default=1,
    show_default=True,
    help="Records generated in parallel. Each record is two sequential API calls.",
)
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("out"), show_default=True)
@click.option("--model", default=DEFAULT_MODEL, show_default=True)
@click.option(
    "--coder-model",
    default=None,
    help="Run stage B (code selection) on a different model from stage A.",
)
@click.option("--template", type=click.Path(exists=True, path_type=Path), default=DEFAULT_TEMPLATE)
@click.option("--manifest", "manifest_path", type=click.Path(path_type=Path), default=None)
@click.option("--validate/--no-validate", default=True, show_default=True)
@click.option("--seed", type=int, default=None, help="Seed for mutation choices.")
@click.option(
    "--mode",
    type=click.Choice(["two_stage", "direct"]),
    default="two_stage",
    show_default=True,
    help="two_stage: model picks values, renderer builds the XML (recommended). "
    "direct: model writes the XML itself - measurably worse, kept for comparison.",
)
@click.option(
    "--shots",
    type=int,
    default=0,
    show_default=True,
    help="direct mode only: number of worked (profile, XML) exemplars to include.",
)
@click.option("--dry-run", is_flag=True, help="Estimate prompt size and cost, make no API calls.")
def generate_cmd(
    profile_name: str,
    scenario_text: str | None,
    scenario_file: Path | None,
    count: int,
    concurrency: int,
    out_dir: Path,
    model: str,
    coder_model: str | None,
    template: Path,
    manifest_path: Path | None,
    validate: bool,
    seed: int | None,
    mode: str,
    shots: int,
    dry_run: bool,
) -> None:
    """Generate N synthetic PCRs for one quality profile."""
    if not scenario_text and not scenario_file:
        raise click.UsageError("give --scenario or --scenario-file")

    config = load_profiles()
    try:
        profile = config.get(profile_name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    scenario = (
        Scenario.from_file(scenario_file) if scenario_file else Scenario.from_text(scenario_text)
    )
    registry = load_registry()

    if dry_run:
        cached = build_cached_system(registry)
        cached_tokens = len(cached) // 4
        click.echo(f"profile:        {profile.name} (narrative {profile.narrative_quality}/5)")
        click.echo(f"scenario:       {scenario.name}")
        click.echo(f"cached system:  ~{cached_tokens:,} tokens, sent once then cached")
        click.echo(f"calls:          {count * 2} ({count} records x 2 stages)")
        click.echo(
            "Cache reads are billed at a fraction of input rate, so the catalogue is "
            "paid for roughly once per run rather than once per call."
        )
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(manifest_path or Path("manifest") / f"{profile.name}.jsonl")
    try:
        client = ApiClient(model=model)
        coder = ApiClient(model=coder_model) if coder_model else None
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    def produce(index: int) -> tuple[dict, bool]:
        """Generate, mutate and validate one record. Never raises - a failed
        record is a manifest row, not a crashed run."""
        name = f"{profile.name}_{index + 1:03d}.xml"
        path = out_dir / name
        row: dict = {
            "file": str(path),
            "profile": profile.name,
            "family": profile.family,
            "narrative_quality": profile.narrative_quality,
            "expected_findings": list(profile.expected_findings),
            "ingestible": profile.ingestible,
            "scenario": scenario.to_json(),
            "model": model,
            "coder_model": coder_model or model,
            "template": str(template),
            "mode": mode,
        }

        try:
            if mode == "direct":
                data = generate_direct(
                    client,
                    scenario,
                    profile,
                    config,
                    registry,
                    load_system_base(),
                    load_exemplars(limit=shots) if shots else [],
                )
                row["shots"] = shots
            else:
                result = generate_record(
                    client, scenario, profile, config, registry, template=template, coder=coder
                )
                data = result.xml
                row["unknown_codes"] = result.unknown_codes
                row["render_report"] = result.render_report.to_json()
                row["off_defined_list"] = result.off_defined_list
                row["not_applicable"] = result.not_applicable
                row["timeline"] = result.timeline
                row["narrative"] = result.clinical.get("narrative", "")
        except OutputContractError as exc:
            row.update(status="output_contract_violation", error=str(exc), raw=exc.raw[:2000])
            return row, False
        except Exception as exc:  # noqa: BLE001 - a failed record is data, not a crash
            row.update(status="generation_error", error=f"{type(exc).__name__}: {exc}")
            return row, False

        if profile.mutation is not None:
            data, description = apply_mutation(
                profile.mutation.name, data, registry, profile.mutation.params, seed=seed
            )
            row["mutation"] = {"name": profile.mutation.name, "applied": description}

        path.write_bytes(data)

        if validate:
            outcome = validate_file(path, registry=registry)
            row["validation"] = outcome.to_json()
            row["expected_valid"] = profile.expects_valid
            row["matched_expectation"] = outcome.ok == profile.expects_valid

        row["status"] = "ok"
        row["usage"] = client.usage.to_json()
        if coder is not None:
            row["coder_usage"] = coder.usage.to_json()
        return row, True

    def report(row: dict) -> None:
        name = Path(row["file"]).name
        if row["status"] != "ok":
            click.echo(f"FAIL  {name}  {row.get('error', row['status'])}")
        elif "validation" not in row:
            click.echo(f"WROTE {name}")
        else:
            # A tier is correct when the file's ingestibility matches its intent -
            # so an ingestion_guard record that fails to load is a PASS.
            matched = row["matched_expectation"]
            status = "OK  " if matched else "WRONG"
            detail = "ingests" if row["validation"]["ok"] else "rejected at ingest"
            flag = "" if matched else "  !! did not match profile expectation"
            click.echo(f"{status}  {name:34} {detail}{flag}")

    written = 0
    if concurrency > 1:
        # Each record is two sequential calls; parallelism is across records.
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(produce, i): i for i in range(count)}
            for future in as_completed(futures):
                row, produced = future.result()
                written += produced
                manifest.append(row)
                report(row)
    else:
        for index in range(count):
            row, produced = produce(index)
            written += produced
            manifest.append(row)
            report(row)

    click.echo(f"\n{written}/{count} written to {out_dir}")
    click.echo(f"manifest: {manifest.path}")
    click.echo(f"tokens: {json.dumps(client.usage.to_json())}")


if __name__ == "__main__":
    cli()
