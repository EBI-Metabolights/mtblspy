from pathlib import Path

import click

from mtblspy.commands.submissions.client import SubmissionClient, format_validation_error


def jwt_token_option(function):
    return click.option(
        "--jwt-token",
        envvar="MTBLS_JWT_TOKEN",
        help="Existing submission API JWT token to use and store for this command.",
    )(function)


def create_submission_client(base_url=None, jwt_token=None):
    client = SubmissionClient(base_url=base_url)
    if jwt_token:
        client.login_with_jwt(jwt_token, fetch_api_token=True)
    return client


def echo_validation_errors(errors, err=False):
    for error in errors[:5]:
        click.echo(f"- {format_validation_error(error)}", err=err)
    if len(errors) > 5:
        click.echo(f"- ... and {len(errors) - 5} more error(s)", err=err)


def echo_report(validation_file_path):
    with Path(validation_file_path).open("r", encoding="utf-8") as validation_file:
        for line in validation_file:
            click.echo(line.rstrip())


def get_created_study_id(result):
    studies = result.get("studies")
    if isinstance(studies, dict) and studies:
        return ", ".join(studies.keys())
    return result.get("study_id") or result.get("accession")
