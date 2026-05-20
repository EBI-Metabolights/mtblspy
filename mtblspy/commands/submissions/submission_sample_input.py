import click

from mtblspy.commands.submissions.client import DEFAULT_STUDY_INPUT_DATA_FOLDER, save_sample_study_input


@click.command(name="sample-input")
@click.option(
    "--data-folder",
    "-d",
    default=str(DEFAULT_STUDY_INPUT_DATA_FOLDER),
    show_default=True,
    type=click.Path(file_okay=False),
    help="Folder where study_input.json will be written.",
)
@click.option("--overwrite/--no-overwrite", default=True, show_default=True, help="Overwrite an existing study_input.json.")
def sample_study_input(data_folder, overwrite):
    """Create a sample study creation JSON input file."""
    try:
        output_path = save_sample_study_input(data_folder=data_folder, overwrite=overwrite)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Sample study input JSON saved to {output_path}")
