import os

import click

from mtblspy.commands.submissions.client import SubmissionClient
from mtblspy.config import DEFAULT_BASE_URL, clear_session


@click.command(name="logout")
@click.option("--base-url", default=DEFAULT_BASE_URL, show_default=True, help="MetaboLights REST API base URL.")
def logout(base_url):
    """Clear stored MetaboLights authentication credentials."""
    try:
        client = SubmissionClient(base_url=base_url)
        clear_session(
            client.rest_api_base_url,
            client.submission_api_base_url,
            credential_base_url=client.credential_base_url,
        )
        click.echo("Logged out. Stored MetaboLights tokens and user cleared from system keyring.")

        active_env_vars = [
            name
            for name in ("MTBLS_API_KEY", "MTBLS_USER", "MTBLS_USERNAME")
            if os.getenv(name)
        ]
        if active_env_vars:
            click.echo(
                "Note: environment variables still provide credentials: "
                + ", ".join(active_env_vars)
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
