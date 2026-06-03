import click

from mtblspy.commands.auth.login import login
from mtblspy.commands.auth.logout import logout


@click.group(name="auth")
def auth_cli():
    """Authentication management."""


auth_cli.add_command(login)
auth_cli.add_command(logout)
