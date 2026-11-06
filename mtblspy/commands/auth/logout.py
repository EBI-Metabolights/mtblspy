import os

import click

from mtblspy.commands.submissions.client import SubmissionClient
from mtblspy.config import clear_session
from mtblspy.credentials import CredentialStore


@click.command(name="logout")
@click.option(
    "--base-url",
    help="MetaboLights REST API base URL.",
)
@click.option(
    "--all",
    "all_sessions",
    is_flag=True,
    help="Sign out of every known server session.",
)
def logout(base_url, all_sessions):
    """Sign out of MetaboLights."""
    if all_sessions and base_url:
        raise click.UsageError("Use either --all or --base-url.")
    try:
        if all_sessions:
            CredentialStore.clear_all_sessions()
            click.echo("Logged out of all known sessions.")
        else:
            client = SubmissionClient(base_url=base_url)
            clear_session(
                client.rest_api_base_url,
                client.submission_api_base_url,
                credential_base_url=client.credential_base_url,
            )
            click.echo(f"Logged out of {client.rest_api_base_url}.")

        active_env_vars = [
            name
            for name in (
                "MTBLS_API_KEY",
                "MTBLS_USER",
                "MTBLS_USERNAME",
                "MTBLS_JWT_TOKEN",
                "MTBLS_REFRESH_TOKEN",
                "MTBLS_TOKEN_FILE",
            )
            if os.getenv(name)
        ]
        if active_env_vars:
            click.echo(
                "Note: environment variables still provide credentials: "
                + ", ".join(active_env_vars)
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
