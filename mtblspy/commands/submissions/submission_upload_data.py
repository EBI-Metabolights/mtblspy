import json

import click

from mtblspy.commands.output import save_json_output
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    SubmissionClient,
    normalize_study_id,
    parse_comma_separated_values,
)
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.command(name="upload-data")
@click.argument("study_id")
@click.option(
    "--data-files-root-path",
    required=True,
    type=click.Path(exists=False, file_okay=False),
    help="Root path of data files to upload.",
)
@click.option(
    "--selected-files",
    type=str,
    help="Comma-separated file or folder paths under the data files root to upload.",
)
@click.option(
    "--skip-uploaded-files",
    type=str,
    help="Comma-separated file or folder paths under the data files root to skip.",
)
@click.option(
    "--skip-empty-folders",
    type=str,
    help="Comma-separated empty folder paths under the data files root to skip.",
)
@click.option(
    "--mtbls-submission-endpoint",
    type=str,
    help="MetaboLights REST API endpoint for this upload, overriding configured defaults.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Save upload options and result as JSON. Filename-only values are saved to the study cache.",
)
def upload_data(
    study_id,
    data_files_root_path,
    selected_files,
    skip_uploaded_files,
    skip_empty_folders,
    mtbls_submission_endpoint,
    output,
):
    """Upload study data files to the private FTP area."""
    normalized_study_id = normalize_study_id(study_id)
    normalized_endpoint = normalize_endpoint(mtbls_submission_endpoint)
    selected_file_names = parse_comma_separated_values(selected_files)
    skip_uploaded_file_names = parse_comma_separated_values(skip_uploaded_files)
    skip_empty_folder_names = parse_comma_separated_values(skip_empty_folders)

    try:
        client = SubmissionClient(base_url=normalized_endpoint)
        result = client.upload_data_files(
            study_id,
            data_files_root_path=data_files_root_path,
            selected_files=selected_file_names,
            skip_uploaded_files=skip_uploaded_file_names,
            skip_empty_folders=skip_empty_folder_names,
        )
    except SubmissionError as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        write_failure_output(
            study_id=normalized_study_id,
            data_files_root_path=data_files_root_path,
            selected_files=selected_file_names,
            skip_uploaded_files=skip_uploaded_file_names,
            skip_empty_folders=skip_empty_folder_names,
            mtbls_submission_endpoint=resolved_endpoint,
            output=output,
            message=str(exc),
        )
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        write_failure_output(
            study_id=normalized_study_id,
            data_files_root_path=data_files_root_path,
            selected_files=selected_file_names,
            skip_uploaded_files=skip_uploaded_file_names,
            skip_empty_folders=skip_empty_folder_names,
            mtbls_submission_endpoint=resolved_endpoint,
            output=output,
            message=str(exc),
        )
        raise click.ClickException(str(exc)) from exc

    status = "failed" if result.missing_on_local or result.errors else "success"
    payload = build_upload_data_payload(
        study_id=result.study_id,
        data_files_root_path=data_files_root_path,
        selected_files=selected_file_names,
        skip_uploaded_files=skip_uploaded_file_names,
        skip_empty_folders=skip_empty_folder_names,
        mtbls_submission_endpoint=client.rest_api_base_url,
        output=output,
        status=status,
        uploaded_files=result.uploaded_files,
        skipped_files=result.skipped_files,
        missing_on_local=result.missing_on_local,
        message=build_upload_data_message(result),
    )

    if output:
        output_path = save_upload_data_output(payload, output, result.study_id)
        click.echo(f"Data upload JSON saved to {output_path}")

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


def build_upload_data_message(result):
    if result.missing_on_local:
        return "Some selected data files or folders were missing locally."
    if result.errors:
        return "Data upload completed with errors: " + "; ".join(result.errors)
    return f"Uploaded {len(result.uploaded_files)} data file(s) or folder(s) for {result.study_id}."


def build_upload_data_payload(
    study_id,
    data_files_root_path,
    selected_files,
    skip_uploaded_files,
    skip_empty_folders,
    mtbls_submission_endpoint,
    output,
    status,
    uploaded_files,
    skipped_files,
    missing_on_local,
    message,
):
    return {
        "parameters": [
            {"name": "study_id", "value": study_id},
            {"name": "data_files_root_path", "value": str(data_files_root_path)},
            {"name": "selected_files", "value": selected_files},
            {"name": "skip_uploaded_files", "value": skip_uploaded_files},
            {"name": "skip_empty_folders", "value": skip_empty_folders},
            {"name": "mtbls_submission_endpoint", "value": mtbls_submission_endpoint},
            {"name": "output", "value": output},
        ],
        "status": status,
        "uploaded_files": uploaded_files,
        "Skipped_files": skipped_files,
        "missing_on_local": missing_on_local,
        "message": message,
    }


def save_upload_data_output(payload, output, study_id):
    default_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
    return save_json_output(
        payload,
        output,
        default_directory,
        "data_upload_response.json",
    )


def write_failure_output(
    study_id,
    data_files_root_path,
    selected_files,
    skip_uploaded_files,
    skip_empty_folders,
    mtbls_submission_endpoint,
    output,
    message,
):
    if not output:
        return
    payload = build_upload_data_payload(
        study_id=study_id,
        data_files_root_path=data_files_root_path,
        selected_files=selected_files,
        skip_uploaded_files=skip_uploaded_files,
        skip_empty_folders=skip_empty_folders,
        mtbls_submission_endpoint=mtbls_submission_endpoint,
        output=output,
        status="failed",
        uploaded_files=[],
        skipped_files=[],
        missing_on_local=[],
        message=message,
    )
    output_path = save_upload_data_output(payload, output, study_id)
    click.echo(f"Data upload JSON saved to {output_path}")
