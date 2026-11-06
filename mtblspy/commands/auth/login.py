import sys

import click

from mtblspy.commands.submissions.client import SubmissionClient


def can_prompt():
    return sys.stdin.isatty()


@click.command(name="login")
@click.option(
    "--user",
    "--username",
    "user_name",
    envvar="MTBLS_USER",
    help="MetaboLights username or email.",
)
@click.option("--password", envvar="MTBLS_PASSWORD", help="MetaboLights password.")
@click.option(
    "--jwt-token",
    envvar="MTBLS_JWT_TOKEN",
    help="Use an existing JWT to sign in.",
)
@click.option(
    "--base-url",
    help="MetaboLights REST API base URL. Defaults to MTBLS_BASE_URL or the saved/default server.",
)
@click.option(
    "--refresh-token",
    envvar="MTBLS_REFRESH_TOKEN",
    help="Refresh token associated with the JWT. Prefer the environment variable to avoid shell history.",
)
@click.option(
    "--issuer",
    envvar="MTBLS_OIDC_ISSUER",
    help="OAuth realm issuer URL. Defaults to the selected MetaboLights server.",
)
@click.option(
    "--client-id",
    envvar="MTBLS_OIDC_CLIENT_ID",
    help="OAuth client ID. Defaults to the JWT authorized party, or swagger-ui-test.",
)
@click.option(
    "--token-file",
    type=click.Path(exists=True, dir_okay=False),
    envvar="MTBLS_TOKEN_FILE",
    help="Reuse an existing MCP sign-in session.",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    envvar="MTBLS_NON_INTERACTIVE",
    help="Fail instead of prompting for missing login credentials.",
)
def login(
    user_name,
    password,
    jwt_token,
    base_url,
    refresh_token,
    issuer,
    client_id,
    token_file,
    non_interactive,
):
    """Login to MetaboLights using a username/password or JWT token."""
    if token_file and (jwt_token or refresh_token):
        raise click.UsageError("Use either --token-file or JWT/refresh credentials.")
    if refresh_token and not jwt_token:
        raise click.UsageError(
            "A refresh token requires an access token from the same login."
        )
    if (
        not token_file
        and not jwt_token
        and (not user_name or not password)
        and (non_interactive or not can_prompt())
    ):
        raise click.UsageError(
            "Missing login credentials. Supply environment credentials or --token-file for non-interactive use."
        )
    if not token_file and not jwt_token and not user_name:
        user_name = click.prompt("Please enter your MetaboLights username or email")
    if not token_file and not jwt_token and not password:
        password = click.prompt(
            "Please enter your MetaboLights password", hide_input=True
        )

    try:
        client = SubmissionClient(base_url=base_url)
        click.echo(f"Logging in with {client.rest_api_base_url}...")
        if token_file:
            client.login_with_token_file(token_file, issuer=issuer, client_id=client_id)
        elif jwt_token:
            options = {
                name: value
                for name, value in {
                    "refresh_token": refresh_token,
                    "issuer": issuer,
                    "client_id": client_id,
                }.items()
                if value is not None
            }
            client.login_with_jwt(jwt_token, fetch_api_token=True, **options)
        else:
            client.login(user_name, password)
        click.echo("Login successful.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
