import click

from mtblspy.commands.submissions.client import SubmissionClient


@click.command(name="login")
@click.option("--user", "--username", "user_name", envvar="MTBLS_USER", help="MetaboLights username or email.")
@click.option("--password", envvar="MTBLS_PASSWORD", help="MetaboLights password.")
@click.option("--jwt-token", envvar="MTBLS_JWT_TOKEN", help="Use an existing submission API JWT token.")
@click.option(
    "--base-url",
    help="MetaboLights REST API base URL. Defaults to saved config, MTBLS_BASE_URL, or production.",
)
def login(user_name, password, jwt_token, base_url):
    """Login to MetaboLights using a username/password or JWT token."""
    if not jwt_token and not user_name:
        user_name = click.prompt("Please enter your MetaboLights username or email")
    if not jwt_token and not password:
        password = click.prompt("Please enter your MetaboLights password", hide_input=True)

    try:
        client = SubmissionClient(base_url=base_url)
        click.echo(f"Logging in with {client.rest_api_base_url}...")
        if jwt_token:
            client.login_with_jwt(jwt_token)
        else:
            client.login(user_name, password)
        click.echo("Login successful.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
