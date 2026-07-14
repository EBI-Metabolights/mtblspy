from dataclasses import dataclass, field
from pathlib import Path

import click

from mtblspy.commands.submissions.client import SubmissionClient, format_validation_error

SUBMISSION_CONTEXT_KEY = "submission_context"


@dataclass
class SubmissionClickContext:
    """Shared Click context for submission commands."""

    _clients: dict[tuple[str | None, str | None], SubmissionClient] = field(default_factory=dict)

    def create_client(self, base_url=None, jwt_token=None, factory=None):
        factory = factory or create_submission_client
        key = (base_url, jwt_token)
        if key not in self._clients:
            self._clients[key] = factory(base_url=base_url, jwt_token=jwt_token)
        return self._clients[key]


def ensure_submission_context(ctx):
    ctx.ensure_object(dict)
    return ctx.obj.setdefault(SUBMISSION_CONTEXT_KEY, SubmissionClickContext())


def get_submission_client(ctx, base_url=None, jwt_token=None, factory=None):
    return ensure_submission_context(ctx).create_client(
        base_url=base_url,
        jwt_token=jwt_token,
        factory=factory,
    )


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
