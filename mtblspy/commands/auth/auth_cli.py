import click

from mtblspy.commands.auth.login import login


@click.group(name="auth")
def auth_cli():
    """Authentication management."""


auth_cli.add_command(login)
