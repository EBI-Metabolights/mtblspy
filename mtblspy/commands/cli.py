import click
from mtblspy import __version__
from mtblspy.commands.auth.auth_cli import auth_cli
from mtblspy.commands.config.config_cli import config_cli
from mtblspy.commands.submissions.submission_cli import submission_cli

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__)
def cli():
    """MetaboLights Submission CLI.
    
    A command line interface for creating, listing, and submitting studies 
    to MetaboLights.
    """
    pass

cli.add_command(auth_cli)
cli.add_command(config_cli)
cli.add_command(submission_cli)

if __name__ == "__main__":
    cli()
