import json

import click

from mtblspy.commands.output import save_json_output
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    SubmissionClient,
    normalize_study_id,
)
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.command(name="clean-ftp-temp-files")
@click.argument("study_id")
@click.option(
    "--mtbls-submission-endpoint",
    type=str,
    help="MetaboLights REST API endpoint for FTP credentials, overriding configured defaults.",
)
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Save cleanup options and result as JSON. Filename-only values are saved to the current directory.",
)
def clean_ftp_temp_files(study_id, mtbls_submission_endpoint, base_url, output):
    """Delete incomplete .ftp_ temporary files from the study private FTP area."""
    normalized_study_id = normalize_study_id(study_id)
    normalized_endpoint = normalize_endpoint(mtbls_submission_endpoint or base_url)

    try:
        client = SubmissionClient(base_url=normalized_endpoint)
        result = client.clear_ftp_temporary_files(study_id)
    except SubmissionError as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        payload = build_clean_ftp_temp_files_payload(
            study_id=normalized_study_id,
            mtbls_submission_endpoint=resolved_endpoint,
            output=output,
            status="failed",
            deleted_files=[],
            message=str(exc),
            errors=[str(exc)],
        )
        save_clean_ftp_temp_files_output_if_requested(payload, output, normalized_study_id)
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc
    except Exception as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        payload = build_clean_ftp_temp_files_payload(
            study_id=normalized_study_id,
            mtbls_submission_endpoint=resolved_endpoint,
            output=output,
            status="failed",
            deleted_files=[],
            message=str(exc),
            errors=[str(exc)],
        )
        save_clean_ftp_temp_files_output_if_requested(payload, output, normalized_study_id)
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc

    status = "failed" if result.errors else "success"
    payload = build_clean_ftp_temp_files_payload(
        study_id=result.study_id,
        mtbls_submission_endpoint=client.rest_api_base_url,
        output=output,
        status=status,
        deleted_files=result.deleted_files,
        message=build_clean_ftp_temp_files_message(result),
        errors=result.errors,
    )
    save_clean_ftp_temp_files_output_if_requested(payload, output, result.study_id)
    click.echo(json.dumps(payload, indent=2))


def build_clean_ftp_temp_files_message(result):
    if result.errors:
        return "FTP temporary file cleanup completed with errors: " + "; ".join(result.errors)
    return f"Deleted {len(result.deleted_files)} FTP temporary file(s) for {result.study_id}."


def build_clean_ftp_temp_files_payload(
    study_id,
    mtbls_submission_endpoint,
    output,
    status,
    deleted_files,
    message,
    errors=None,
):
    errors = list(errors or [])
    return {
        "parameters": [
            {"name": "study_id", "value": study_id},
            {"name": "mtbls_submission_endpoint", "value": mtbls_submission_endpoint},
            {"name": "output", "value": output},
        ],
        "status": status,
        "deleted_files": deleted_files,
        "message": message,
        "errors": errors,
    }


def save_clean_ftp_temp_files_output_if_requested(payload, output, study_id):
    if not output:
        return None
    output_path = save_json_output(
        payload,
        output,
        DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id,
        "clean_ftp_temp_files_response.json",
    )
    click.echo(f"FTP temporary cleanup JSON saved to {output_path}")
    return output_path


def normalize_endpoint(endpoint):
    if not endpoint:
        return None
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint:
        return None
    if "://" not in endpoint:
        return f"https://{endpoint}"
    return endpoint
