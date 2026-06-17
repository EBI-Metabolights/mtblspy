import click

from mtblspy.commands.submissions.client import SubmissionClient


@click.command(name="login")
@click.option("--user", "--username", "user_name", envvar="MTBLS_USER", help="MetaboLights username or email.")
@click.option("--password", envvar="MTBLS_PASSWORD", help="MetaboLights password.")
@click.option(
    "--base-url",
    help="MetaboLights REST API base URL. Defaults to saved config, MTBLS_BASE_URL, or production.",
)
def login(user_name, password, base_url):
    """Login to MetaboLights using a username and password."""
    if not user_name:
        user_name = click.prompt("Please enter your MetaboLights username or email")
    if not password:
        password = click.prompt("Please enter your MetaboLights password", hide_input=True)

    try:
        client = SubmissionClient(base_url=base_url)
        click.echo(f"Logging in with {client.rest_api_base_url}...")
        client.login(user_name, password)
        click.echo("Login successful. Tokens and user saved to system keyring.")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
