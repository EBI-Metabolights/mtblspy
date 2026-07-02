import json
from pathlib import Path

import click

from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_DATA_PATH,
    VALIDATION_MAX_POLLS,
    VALIDATION_POLL_INTERVAL_SECONDS,
    SubmissionClient,
    normalize_study_id,
)
from mtblspy.commands.submissions.local_validation import (
    DEFAULT_VALIDATION_BUNDLE_PATH,
    DEFAULT_VALIDATION_BUNDLE_URL,
    LOCAL_VALIDATION_TIMEOUT_SECONDS,
    run_local_validation,
)


@click.command(name="validate", short_help="Run study validation.")
@click.argument("study_id")
@click.option(
    "--default-submission-data-path",
    type=click.Path(file_okay=False),
    default=str(DEFAULT_LOCAL_SUBMISSION_DATA_PATH),
    show_default=True,
    help="Parent folder for local study metadata folders.",
)
@click.option(
    "--metadata-files-path",
    "--metadata-path",
    "-p",
    type=click.Path(exists=False, file_okay=False),
    help="Local ISA-Tab metadata directory. Defaults to <default-submission-data-path>/<study-id>.",
)
@click.option(
    "--data-files-root-path",
    type=click.Path(exists=False, file_okay=False),
    help="Root path of data files used by local validation. Required unless --remote-validation is used.",
)
@click.option(
    "--remote-validation",
    is_flag=True,
    default=False,
    help="Run validation through the remote submission API instead of local validation.",
)
@click.option(
    "--mtbls-validation-wasm-path",
    type=click.Path(dir_okay=False),
    help=(
        "Local MetaboLights standalone WASM or OPA WASM bundle path. "
        "OPA WASM bundles require an OPA executable with WebAssembly support."
    ),
)
@click.option(
    "--mtbls-validation-wasm-url",
    type=str,
    help="URL used to download the validation standalone WASM or OPA WASM bundle when the local WASM path is missing.",
)
@click.option(
    "--mtbls-validation-endpoint",
    type=str,
    help="MetaboLights validation API endpoint for remote validation, overriding the submission API endpoint.",
)
@click.option(
    "--mtbls-submission-endpoint",
    type=str,
    help="MetaboLights submission REST API endpoint for remote validation, overriding configured defaults.",
)
@click.option(
    "--validation-bundle-path",
    "--mtbls-validation-bundle-path",
    default=DEFAULT_VALIDATION_BUNDLE_PATH,
    show_default=True,
    help="Local MetaboLights validation bundle path for default OPA validation.",
)
@click.option(
    "--validation-bundle-url",
    "--mtbls-validation-bundle-url",
    default=DEFAULT_VALIDATION_BUNDLE_URL,
    show_default=True,
    help="URL used to download the OPA validation bundle when it is missing.",
)
@click.option(
    "--refetch-validation-bundle",
    is_flag=True,
    default=False,
    help="Download the OPA validation bundle even if --validation-bundle-path already exists.",
)
@click.option(
    "--opa-executable-path",
    default="opa",
    show_default=True,
    help="OPA executable path for default bundle validation and OPA WASM bundle validation.",
)
@click.option(
    "--validation-input-path",
    type=click.Path(dir_okay=False),
    help="Path to save the generated local validation input JSON.",
)
@click.option(
    "--config-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Optional configuration file with validation overrides.",
)
@click.option(
    "--overridden-rules-file-path",
    type=click.Path(exists=True, dir_okay=False),
    help="Text file with validation rule identifiers or metadata filenames to ignore.",
)
@click.option("--max-polls", default=VALIDATION_MAX_POLLS, show_default=True, help="Maximum remote validation status checks.")
@click.option(
    "--poll-interval",
    default=VALIDATION_POLL_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds between remote validation status checks.",
)
@click.option("--timeout", default=LOCAL_VALIDATION_TIMEOUT_SECONDS, show_default=True, help="Local validation timeout in seconds.")
@click.option(
    "--output",
    "--validation-file-path",
    "--validation_file_path",
    "-o",
    "-v",
    type=click.Path(dir_okay=False),
    help="Path to save the validation report JSON. Filename-only values are saved to the study cache.",
)
@click.option("--output-format", type=click.Choice(["json"]), default="json", show_default=True, help="Validation output format.")
def validate_submission(
    study_id,
    default_submission_data_path,
    metadata_files_path,
    data_files_root_path,
    remote_validation,
    mtbls_validation_wasm_path,
    mtbls_validation_wasm_url,
    mtbls_validation_endpoint,
    mtbls_submission_endpoint,
    validation_bundle_path,
    validation_bundle_url,
    refetch_validation_bundle,
    opa_executable_path,
    validation_input_path,
    config_file,
    overridden_rules_file_path,
    max_polls,
    poll_interval,
    timeout,
    output,
    output_format,
):
    """Run local validation by default, or remote validation with --remote-validation."""
    del output_format
    normalized_study_id = normalize_study_id(study_id)

    try:
        if remote_validation:
            result = run_remote_validation(
                study_id,
                output,
                mtbls_submission_endpoint,
                mtbls_validation_endpoint,
                max_polls,
                poll_interval,
            )
        else:
            if not data_files_root_path:
                raise click.ClickException(
                    "--data-files-root-path is required unless --remote-validation is used."
                )
            result = run_default_local_validation(
                study_id,
                default_submission_data_path,
                metadata_files_path,
                data_files_root_path,
                validation_bundle_path,
                validation_bundle_url,
                refetch_validation_bundle,
                opa_executable_path,
                mtbls_validation_wasm_path,
                mtbls_validation_wasm_url,
                output,
                validation_input_path,
                config_file,
                overridden_rules_file_path,
                timeout,
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    report = load_json_report(result.report_path)
    report.setdefault("accession", normalized_study_id)
    click.echo(json.dumps(report, indent=2))


def run_remote_validation(
    study_id,
    output,
    mtbls_submission_endpoint,
    mtbls_validation_endpoint,
    max_polls,
    poll_interval,
):
    client = SubmissionClient(base_url=normalize_endpoint(mtbls_submission_endpoint))
    validation_endpoint = normalize_endpoint(mtbls_validation_endpoint)
    if validation_endpoint:
        client.submission_api_base_url = validation_endpoint
    return client.validate_study(
        study_id,
        validation_file_path=output,
        max_polls=max_polls,
        poll_interval=poll_interval,
    )


def run_default_local_validation(
    study_id,
    default_submission_data_path,
    metadata_files_path,
    data_files_root_path,
    validation_bundle_path,
    validation_bundle_url,
    refetch_validation_bundle,
    opa_executable_path,
    mtbls_validation_wasm_path,
    mtbls_validation_wasm_url,
    output,
    validation_input_path,
    config_file,
    overridden_rules_file_path,
    timeout,
):
    return run_local_validation(
        study_id,
        metadata_path=metadata_files_path,
        data_files_path=data_files_root_path,
        default_submission_data_path=default_submission_data_path,
        validation_bundle_path=validation_bundle_path,
        validation_bundle_url=validation_bundle_url,
        refetch_validation_bundle=refetch_validation_bundle,
        opa_executable_path=opa_executable_path,
        validation_wasm_path=mtbls_validation_wasm_path,
        validation_wasm_url=mtbls_validation_wasm_url,
        validation_file_path=output,
        validation_input_path=validation_input_path,
        config_file=config_file,
        overridden_rules_file_path=overridden_rules_file_path,
        timeout=timeout,
    )


def normalize_endpoint(endpoint):
    if not endpoint:
        return None
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint:
        return None
    if "://" not in endpoint:
        return f"https://{endpoint}"
    return endpoint


def load_json_report(report_path):
    with Path(report_path).open("r", encoding="utf-8") as report_file:
        return json.load(report_file)
