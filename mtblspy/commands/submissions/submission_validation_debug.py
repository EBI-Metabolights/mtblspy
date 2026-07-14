import click

from mtblspy.commands.output import resolve_json_output_path, write_json_file
from mtblspy.commands.submissions.cli_utils import echo_validation_errors, create_submission_client, jwt_token_option
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    VALIDATION_MAX_POLLS,
    VALIDATION_POLL_INTERVAL_SECONDS,
    get_validation_error_field,
    get_validation_error_message,
    get_validation_error_rule,
    get_validation_error_value,
    get_validation_root_causes,
    normalize_study_id,
)
from mtblspy.commands.submissions.local_validation import (
    DEFAULT_VALIDATION_BUNDLE_PATH,
    DEFAULT_VALIDATION_BUNDLE_URL,
    LOCAL_VALIDATION_TIMEOUT_SECONDS,
    run_local_validation,
)


@click.command(
    name="validation-debug",
    hidden=True,
    short_help="Developer-only remote/local validation root-cause report.",
)
@click.argument("study_id")
@click.option(
    "--metadata-path",
    "-p",
    type=click.Path(exists=True, file_okay=False),
    help="Optional local ISA-Tab metadata directory to compare with remote validation.",
)
@click.option(
    "--data-files-path",
    help="Optional data files root path for local validation. Defaults to <metadata-path>/FILES.",
)
@click.option(
    "--isa-json-file-path",
    "--isa_json_file_path",
    "--isa-output",
    "-i",
    type=click.Path(dir_okay=False),
    help="Path to save the fetched ISA JSON. Defaults to the submission cache as <accession>.json.",
)
@click.option(
    "--validation-file-path",
    "--validation_file_path",
    "--output",
    "-v",
    "-o",
    type=click.Path(dir_okay=False),
    help="Path to save the combined validation debug report. Filename-only values are saved to the current directory.",
)
@click.option(
    "--remote-validation-file-path",
    type=click.Path(dir_okay=False),
    help="Path to save the raw remote validation root-cause report.",
)
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--local-validation-file-path",
    type=click.Path(dir_okay=False),
    help="Path to save the raw local validation report when --metadata-path is used.",
)
@click.option(
    "--local-validation-input-path",
    type=click.Path(dir_okay=False),
    help="Path to save the generated local validation input JSON when --metadata-path is used.",
)
@click.option(
    "--validation-bundle-path",
    default=DEFAULT_VALIDATION_BUNDLE_PATH,
    show_default=True,
    help="Local MetaboLights validation bundle path.",
)
@click.option(
    "--validation-bundle-url",
    default=DEFAULT_VALIDATION_BUNDLE_URL,
    show_default=True,
    help="URL used to download the validation bundle when it is missing.",
)
@click.option(
    "--refetch-validation-bundle",
    is_flag=True,
    default=False,
    help="Download the validation bundle even if --validation-bundle-path already exists.",
)
@click.option("--opa-executable-path", default="opa", show_default=True, help="OPA executable path.")
@click.option("--max-polls", default=VALIDATION_MAX_POLLS, show_default=True, help="Maximum validation status checks.")
@click.option(
    "--poll-interval",
    default=VALIDATION_POLL_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds between validation status checks.",
)
@click.option("--timeout", default=LOCAL_VALIDATION_TIMEOUT_SECONDS, show_default=True, help="Local OPA timeout in seconds.")
@jwt_token_option
def validation_debug(
    study_id,
    metadata_path,
    data_files_path,
    isa_json_file_path,
    validation_file_path,
    remote_validation_file_path,
    base_url,
    local_validation_file_path,
    local_validation_input_path,
    validation_bundle_path,
    validation_bundle_url,
    refetch_validation_bundle,
    opa_executable_path,
    max_polls,
    poll_interval,
    timeout,
    jwt_token,
):
    """Developer helper: compare remote validation with optional local validation."""
    try:
        study_id = normalize_study_id(study_id)
        cache_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
        debug_report_path = resolve_json_output_path(
            validation_file_path,
            cache_directory,
            f"{study_id}_validation_debug.json",
        )
        remote_report_path = remote_validation_file_path or str(cache_directory / f"{study_id}_remote_validation_report.json")

        client = create_submission_client(base_url=base_url, jwt_token=jwt_token)
        click.echo(f"Creating remote validation root-cause report for {study_id}...")
        remote_result = client.find_validation_root_causes(
            study_id,
            isa_json_file_path=isa_json_file_path,
            validation_file_path=remote_report_path,
            max_polls=max_polls,
            poll_interval=poll_interval,
        )

        local_result = None
        local_context = None
        if metadata_path:
            click.echo(f"Running local validation for {study_id}...")
            local_result = run_local_validation(
                study_id,
                metadata_path=metadata_path,
                data_files_path=data_files_path,
                validation_bundle_path=validation_bundle_path,
                validation_bundle_url=validation_bundle_url,
                refetch_validation_bundle=refetch_validation_bundle,
                opa_executable_path=opa_executable_path,
                validation_file_path=local_validation_file_path,
                validation_input_path=local_validation_input_path,
                config_file=None,
                overridden_rules_file_path=None,
                timeout=timeout,
            )
            local_context = build_local_context(metadata_path, data_files_path)

        debug_report = build_validation_debug_report(
            study_id,
            remote_result,
            local_result=local_result,
            local_context=local_context,
        )
        write_json_file(debug_report, debug_report_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    validation_result = remote_result.validation_result
    if validation_result.errors:
        click.echo(f"Remote validation completed with {len(validation_result.errors)} error(s).")
        echo_validation_errors(validation_result.errors)
    else:
        click.echo("Remote validation completed successfully. No validation errors found.")

    if local_result:
        if local_result.errors:
            click.echo(f"Local validation completed with {len(local_result.errors)} error(s).")
            echo_validation_errors(local_result.errors)
        else:
            click.echo("Local validation completed successfully. No validation errors found.")
        click.echo(f"Local validation input is saved as {local_result.validation_input_path}")
        click.echo(f"Local validation report is saved as {local_result.report_path}")

    click.echo(f"ISA JSON is saved as {remote_result.isa_json_path}")
    click.echo(f"Remote validation root-cause report is saved as {validation_result.report_path}")
    click.echo(f"Combined validation debug report is saved as {debug_report_path}")


def build_validation_debug_report(study_id, remote_result, local_result=None, local_context=None):
    remote_errors = remote_result.validation_result.errors
    local_errors = local_result.errors if local_result else []
    comparison = compare_validation_errors(remote_errors, local_errors)
    report = {
        "accession": study_id,
        "summary": {
            "remoteErrorCount": len(remote_errors),
            "localErrorCount": len(local_errors),
            "sharedErrorCount": len(comparison["sharedErrors"]),
            "remoteOnlyErrorCount": len(comparison["remoteOnlyErrors"]),
            "localOnlyErrorCount": len(comparison["localOnlyErrors"]),
        },
        "remote": {
            "reportPath": str(remote_result.validation_result.report_path),
            "isaJsonPath": str(remote_result.isa_json_path),
            "errors": remote_errors,
            "rootCauses": get_validation_root_causes(remote_errors) if remote_errors else [],
        },
        "comparison": comparison,
        "diagnosis": build_diagnosis(comparison, bool(local_result), local_context),
    }
    if local_result:
        report["local"] = {
            "reportPath": str(local_result.report_path),
            "validationInputPath": str(local_result.validation_input_path),
            "context": local_context,
            "errors": local_errors,
            "rootCauses": get_validation_root_causes(local_errors) if local_errors else [],
        }
    return report


def compare_validation_errors(remote_errors, local_errors):
    remote_by_key = {validation_error_key(error): error for error in remote_errors}
    local_by_key = {validation_error_key(error): error for error in local_errors}
    shared_keys = sorted(set(remote_by_key) & set(local_by_key))
    remote_only_keys = sorted(set(remote_by_key) - set(local_by_key))
    local_only_keys = sorted(set(local_by_key) - set(remote_by_key))
    return {
        "sharedErrors": [comparison_item(remote_by_key[key], local_by_key[key]) for key in shared_keys],
        "remoteOnlyErrors": [debug_error(remote_by_key[key]) for key in remote_only_keys],
        "localOnlyErrors": [debug_error(local_by_key[key]) for key in local_only_keys],
    }


def validation_error_key(error):
    return (
        get_validation_error_rule(error) or "",
        error.get("sourceFile") or error.get("source_file") or error.get("metadata_file") or "",
        get_validation_error_field(error) or "",
        get_validation_error_message(error) or "",
    )


def comparison_item(remote_error, local_error):
    return {
        "rule": get_validation_error_rule(remote_error) or get_validation_error_rule(local_error),
        "sourceFile": remote_error.get("sourceFile") or local_error.get("sourceFile"),
        "field": get_validation_error_field(remote_error) or get_validation_error_field(local_error),
        "message": get_validation_error_message(remote_error) or get_validation_error_message(local_error),
        "remote": debug_error(remote_error),
        "local": debug_error(local_error),
    }


def debug_error(error):
    return {
        "rule": get_validation_error_rule(error),
        "section": error.get("section"),
        "sourceFile": error.get("sourceFile") or error.get("source_file") or error.get("metadata_file"),
        "field": get_validation_error_field(error),
        "message": get_validation_error_message(error),
        "value": get_validation_error_value(error),
        "raw": error,
    }


def build_local_context(metadata_path, data_files_path):
    from pathlib import Path

    metadata = Path(metadata_path).expanduser().resolve()
    data = Path(data_files_path).expanduser() if data_files_path else metadata / "FILES"
    if not data.is_absolute():
        data = metadata / data
    data = data.resolve()
    return {
        "metadataPath": str(metadata),
        "dataFilesPath": str(data),
        "dataFilesPathExists": data.exists(),
    }


def build_diagnosis(comparison, has_local_result, local_context):
    diagnosis = []
    if not has_local_result:
        diagnosis.append(
            {
                "type": "remote-only",
                "message": "No local metadata path was provided, so validation-debug could not compare remote errors with local files.",
            }
        )
        return diagnosis
    if comparison["sharedErrors"]:
        diagnosis.append(
            {
                "type": "shared",
                "message": "Errors in sharedErrors reproduce locally and remotely. These are likely caused by metadata/data content common to both environments.",
            }
        )
    if comparison["remoteOnlyErrors"]:
        diagnosis.append(
            {
                "type": "remote-only",
                "message": "Errors in remoteOnlyErrors exist only in the server validation result. These may come from server-side DB/MHD context or files uploaded to the server that are not represented in the local folder.",
            }
        )
    if comparison["localOnlyErrors"]:
        message = "Errors in localOnlyErrors exist only in local validation. These usually mean the local folder differs from the uploaded server study."
        if local_context and not local_context.get("dataFilesPathExists"):
            message += " The local data files path does not exist, so local data-file errors are expected."
        diagnosis.append({"type": "local-only", "message": message})
    return diagnosis
