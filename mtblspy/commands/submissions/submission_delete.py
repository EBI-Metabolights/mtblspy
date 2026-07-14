import json

import click

from mtblspy.commands.submissions.cli_utils import create_submission_client, jwt_token_option
from mtblspy.commands.submissions.exceptions import SubmissionAPIError, SubmissionError


@click.group(name="delete")
def delete_submission():
    """Delete study metadata or data files."""


@delete_submission.command(name="metadata")
@click.argument("study_id")
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--files",
    "selected_files",
    required=True,
    help="Comma-separated metadata filenames to delete.",
)
@jwt_token_option
def delete_metadata(study_id, base_url, selected_files, jwt_token):
    """Delete ISA-Tab metadata files from a study."""
    try:
        client = create_submission_client(base_url=base_url, jwt_token=jwt_token)
        result = client.delete_metadata_files(
            study_id,
            selected_files=selected_files,
        )
    except SubmissionAPIError as exc:
        payload = {
            "study_id": study_id,
            "status": "failed",
            "deleted_files": [],
            "missing_files": [],
            "message": str(exc),
            "errors": get_exception_errors(exc),
        }
        click.echo(json.dumps(payload, indent=2))
        raise click.exceptions.Exit(1) from exc
    except SubmissionError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(json.dumps(delete_result_payload(result), indent=2))


def delete_result_payload(result):
    return {
        "study_id": result.study_id,
        "status": "failed" if result.errors or result.missing_files else "success",
        "deleted_files": result.deleted_files,
        "missing_files": result.missing_files,
        "message": build_delete_message(result),
        "errors": result.errors,
    }


def build_delete_message(result):
    file_count = len(result.deleted_files)
    parts = [f"Deleted {file_count} metadata file(s) for {result.study_id}."]
    if result.missing_files:
        parts.append(f"Missing {len(result.missing_files)} requested file(s): " + ", ".join(result.missing_files))
    if result.errors:
        parts.append(f"Encountered {len(result.errors)} error(s).")
    return " ".join(parts)


def get_exception_errors(exc):
    return getattr(exc, "errors", None) or [str(exc)]
