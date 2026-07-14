import json
from pathlib import Path

import click

from mtblspy.commands.output import save_json_output
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    DEFAULT_LOCAL_SUBMISSION_DATA_PATH,
    normalize_study_id,
    parse_selected_metadata_files,
)
from mtblspy.commands.submissions.cli_utils import create_submission_client, get_submission_client, jwt_token_option
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.command(name="metadata-upload")
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
    type=click.Path(exists=False),
    help="Metadata folder path. Defaults to <default-submission-data-path>/<study-id>.",
)
@click.option(
    "--mtbls-submission-endpoint",
    type=str,
    help="MetaboLights REST API endpoint for this upload, overriding configured defaults.",
)
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--selected-files",
    type=str,
    help="Comma-separated metadata file names in the metadata folder to upload.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Save upload options and result as JSON. Filename-only values are saved to the current directory.",
)
@jwt_token_option
@click.pass_context
def upload_metadata(
    ctx,
    study_id,
    default_submission_data_path,
    metadata_files_path,
    mtbls_submission_endpoint,
    base_url,
    selected_files,
    output,
    jwt_token,
):
    """Upload ISA-Tab metadata files for a study."""
    normalized_endpoint = normalize_endpoint(mtbls_submission_endpoint or base_url)
    selected_file_names = parse_selected_metadata_files(selected_files)
    normalized_study_id = normalize_study_id(study_id)
    metadata_path = metadata_files_path or str(
        Path(default_submission_data_path).expanduser() / normalized_study_id
    )

    try:
        client = get_submission_client(ctx, base_url=normalized_endpoint, jwt_token=jwt_token, factory=create_submission_client)
        result = client.upload_metadata(
            study_id,
            metadata_path=metadata_files_path,
            selected_files=selected_file_names,
            default_submission_data_path=default_submission_data_path,
        )
    except SubmissionError as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        payload = write_failure_output(
            study_id=normalized_study_id,
            default_submission_data_path=default_submission_data_path,
            metadata_files_path=metadata_path,
            mtbls_submission_endpoint=resolved_endpoint,
            selected_files=selected_file_names,
            output=output,
            message=str(exc),
            errors=get_exception_errors(exc),
        )
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc
    except Exception as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        payload = write_failure_output(
            study_id=normalized_study_id,
            default_submission_data_path=default_submission_data_path,
            metadata_files_path=metadata_path,
            mtbls_submission_endpoint=resolved_endpoint,
            selected_files=selected_file_names,
            output=output,
            message=str(exc),
            errors=get_exception_errors(exc),
        )
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc

    payload = build_upload_metadata_payload(
        study_id=result.study_id,
        default_submission_data_path=default_submission_data_path,
        metadata_files_path=metadata_path,
        mtbls_submission_endpoint=client.rest_api_base_url,
        selected_files=selected_file_names,
        output=output,
        status="success",
        uploaded_files=[file_path.name for file_path in result.uploaded_files],
        skipped_files=[file_path.name for file_path in result.skipped_files],
        message=f"Uploaded {len(result.uploaded_files)} metadata file(s) for {result.study_id}.",
        errors=[],
    )

    if output:
        output_path = save_metadata_upload_output(payload, output, result.study_id)
        click.echo(f"Metadata upload JSON saved to {output_path}")

    click.echo(json.dumps(payload, indent=2))


def normalize_endpoint(endpoint):
    if not endpoint:
        return None
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint:
        return None
    if "://" not in endpoint:
        return f"https://{endpoint}"
    return endpoint


def build_upload_metadata_payload(
    study_id,
    default_submission_data_path,
    metadata_files_path,
    mtbls_submission_endpoint,
    selected_files,
    output,
    status,
    uploaded_files,
    skipped_files,
    message,
    errors=None,
):
    errors = list(errors or [])
    return {
        "parameters": [
            {"name": "study_id", "value": study_id},
            {"name": "default_submission_data_path", "value": str(default_submission_data_path)},
            {"name": "metadata_files_path", "value": str(metadata_files_path)},
            {"name": "mtbls_submission_endpoint", "value": mtbls_submission_endpoint},
            {"name": "selected_files", "value": selected_files},
            {"name": "output", "value": output},
        ],
        "status": status,
        "uploaded_files": uploaded_files,
        "skipped_files": skipped_files,
        "message": message,
        "errors": errors,
    }


def save_metadata_upload_output(payload, output, study_id):
    default_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
    return save_json_output(
        payload,
        output,
        default_directory,
        "metadata_upload_response.json",
    )


def write_failure_output(
    study_id,
    default_submission_data_path,
    metadata_files_path,
    mtbls_submission_endpoint,
    selected_files,
    output,
    message,
    errors=None,
):
    payload = build_upload_metadata_payload(
        study_id=study_id,
        default_submission_data_path=default_submission_data_path,
        metadata_files_path=metadata_files_path,
        mtbls_submission_endpoint=mtbls_submission_endpoint,
        selected_files=selected_files,
        output=output,
        status="failed",
        uploaded_files=[],
        skipped_files=[],
        message=message,
        errors=errors or [message],
    )
    if output:
        output_path = save_metadata_upload_output(payload, output, study_id)
        click.echo(f"Metadata upload JSON saved to {output_path}")
    return payload


def get_exception_errors(exc):
    return getattr(exc, "errors", None) or [str(exc)]
