import json

import click
from tqdm import tqdm

from mtblspy.commands.output import save_json_output
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    SubmissionClient,
    normalize_study_id,
    parse_comma_separated_values,
)
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.command(name="data-upload")
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
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Save upload options and result as JSON. Filename-only values are saved to the current directory.",
)
@click.option(
    "--progress/--no-progress",
    default=True,
    show_default=True,
    help="Show an interactive progress bar on stderr while uploading.",
)
def upload_data(
    study_id,
    data_files_root_path,
    selected_files,
    skip_uploaded_files,
    skip_empty_folders,
    mtbls_submission_endpoint,
    base_url,
    output,
    progress,
):
    """Upload study data files to the private FTP area."""
    normalized_study_id = normalize_study_id(study_id)
    normalized_endpoint = normalize_endpoint(mtbls_submission_endpoint or base_url)
    selected_file_names = parse_comma_separated_values(selected_files)
    skip_uploaded_file_names = parse_comma_separated_values(skip_uploaded_files)
    skip_empty_folder_names = parse_comma_separated_values(skip_empty_folders)
    progress_bar = DataUploadProgress(enabled=progress and is_progress_stream_interactive())

    try:
        client = SubmissionClient(base_url=normalized_endpoint)
        upload_kwargs = {
            "data_files_root_path": data_files_root_path,
            "selected_files": selected_file_names,
            "skip_uploaded_files": skip_uploaded_file_names,
            "skip_empty_folders": skip_empty_folder_names,
        }
        if progress_bar.enabled:
            upload_kwargs["progress_callback"] = progress_bar.callback
        result = client.upload_data_files(study_id, **upload_kwargs)
    except SubmissionError as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        payload = write_failure_output(
            study_id=normalized_study_id,
            data_files_root_path=data_files_root_path,
            selected_files=selected_file_names,
            skip_uploaded_files=skip_uploaded_file_names,
            skip_empty_folders=skip_empty_folder_names,
            mtbls_submission_endpoint=resolved_endpoint,
            output=output,
            progress=progress,
            message=str(exc),
            errors=get_exception_errors(exc),
        )
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc
    except Exception as exc:
        resolved_endpoint = client.rest_api_base_url if "client" in locals() else normalized_endpoint
        payload = write_failure_output(
            study_id=normalized_study_id,
            data_files_root_path=data_files_root_path,
            selected_files=selected_file_names,
            skip_uploaded_files=skip_uploaded_file_names,
            skip_empty_folders=skip_empty_folder_names,
            mtbls_submission_endpoint=resolved_endpoint,
            output=output,
            progress=progress,
            message=str(exc),
            errors=get_exception_errors(exc),
        )
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc
    finally:
        progress_bar.close()

    status = "failed" if result.missing_on_local or result.errors else "success"
    payload = build_upload_data_payload(
        study_id=result.study_id,
        data_files_root_path=data_files_root_path,
        selected_files=selected_file_names,
        skip_uploaded_files=skip_uploaded_file_names,
        skip_empty_folders=skip_empty_folder_names,
        mtbls_submission_endpoint=client.rest_api_base_url,
        output=output,
        progress=progress,
        status=status,
        uploaded_files=result.uploaded_files,
        skipped_files=result.skipped_files,
        missing_on_local=result.missing_on_local,
        message=build_upload_data_message(result),
        errors=result.errors,
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
    progress,
    status,
    uploaded_files,
    skipped_files,
    missing_on_local,
    message,
    errors=None,
):
    errors = list(errors or [])
    return {
        "parameters": [
            {"name": "study_id", "value": study_id},
            {"name": "data_files_root_path", "value": str(data_files_root_path)},
            {"name": "selected_files", "value": selected_files},
            {"name": "skip_uploaded_files", "value": skip_uploaded_files},
            {"name": "skip_empty_folders", "value": skip_empty_folders},
            {"name": "mtbls_submission_endpoint", "value": mtbls_submission_endpoint},
            {"name": "output", "value": output},
            {"name": "progress", "value": progress},
        ],
        "status": status,
        "uploaded_files": uploaded_files,
        "skipped_files": skipped_files,
        "missing_on_local": missing_on_local,
        "message": message,
        "errors": errors,
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
    progress,
    message,
    errors=None,
):
    payload = build_upload_data_payload(
        study_id=study_id,
        data_files_root_path=data_files_root_path,
        selected_files=selected_files,
        skip_uploaded_files=skip_uploaded_files,
        skip_empty_folders=skip_empty_folders,
        mtbls_submission_endpoint=mtbls_submission_endpoint,
        output=output,
        progress=progress,
        status="failed",
        uploaded_files=[],
        skipped_files=[],
        missing_on_local=[],
        message=message,
        errors=errors or [message],
    )
    if output:
        output_path = save_upload_data_output(payload, output, study_id)
        click.echo(f"Data upload JSON saved to {output_path}")
    return payload


def get_exception_errors(exc):
    return getattr(exc, "errors", None) or [str(exc)]


def is_progress_stream_interactive():
    return click.get_text_stream("stderr").isatty()


class DataUploadProgress:
    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self.progress_bar = None

    def callback(self, event):
        if not self.enabled:
            return
        event_name = event.get("event")
        if event_name == "start":
            self.start(event.get("total", 0))
        elif event_name == "item":
            self.update(event.get("path", ""), event.get("status", "done"))

    def start(self, total):
        if self.progress_bar is not None:
            return
        stream = click.get_text_stream("stderr")
        self.progress_bar = tqdm(
            total=total,
            desc="Uploading data",
            unit="item",
            file=stream,
            disable=not stream.isatty(),
        )

    def update(self, path, status):
        if self.progress_bar is None:
            self.start(0)
        if self.progress_bar.disable:
            return
        self.progress_bar.set_postfix_str(format_progress_item(path, status), refresh=False)
        self.progress_bar.update(1)

    def close(self):
        if self.progress_bar is not None:
            self.progress_bar.close()
            self.progress_bar = None


def format_progress_item(path, status):
    path = str(path)
    if len(path) > 48:
        path = f"...{path[-45:]}"
    return f"{status}: {path}"
