import click

from mtblspy.commands.submissions.client import SubmissionClient
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.command(name="upload-metadata")
@click.argument("study_id")
@click.argument("metadata_files", nargs=-1, type=click.Path(dir_okay=False))
@click.option(
    "--metadata-path",
    "-p",
    type=click.Path(exists=False),
    help=(
        "Metadata file or directory. Defaults to "
        "~/metabolights_data/submission/data/<study_id>."
    ),
)
def upload_metadata(study_id, metadata_files, metadata_path):
    """Upload ISA-Tab metadata files for a study."""
    try:
        client = SubmissionClient()
        result = client.upload_metadata(
            study_id,
            metadata_path=metadata_path,
            metadata_files=metadata_files,
        )
    except SubmissionError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Uploaded {len(result.uploaded_files)} metadata file(s) for {result.study_id}.")
    for file_path in result.uploaded_files:
        click.echo(f"- {file_path.name}")
