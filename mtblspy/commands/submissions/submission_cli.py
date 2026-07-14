import click

from mtblspy.commands.submissions.cli_utils import ensure_submission_context
from mtblspy.commands.submissions.submission_compress_data_files import compress_data_files
from mtblspy.commands.submissions.submission_check_folders import check_folders
from mtblspy.commands.submissions.submission_clean_ftp_temp_files import clean_ftp_temp_files
from mtblspy.commands.submissions.submission_create import create_submission
from mtblspy.commands.submissions.submission_delete import delete_submission
from mtblspy.commands.submissions.submission_download import download_submission
from mtblspy.commands.submissions.submission_ftp_credentials import private_ftp_credentials
from mtblspy.commands.submissions.submission_list import list_submissions
from mtblspy.commands.submissions.submission_templates import submission_templates
from mtblspy.commands.submissions.submission_upload_data import upload_data
from mtblspy.commands.submissions.submission_upload_metadata import upload_metadata
from mtblspy.commands.submissions.submission_validate import validate_submission
from mtblspy.commands.submissions.submission_validation_debug import validation_debug


@click.group(name="submission")
@click.pass_context
def submission_cli(ctx):
    """Commands to use MetaboLights study submission REST API."""
    ensure_submission_context(ctx)


submission_cli.add_command(list_submissions)
submission_cli.add_command(create_submission)
submission_cli.add_command(delete_submission)
submission_cli.add_command(download_submission)
submission_cli.add_command(private_ftp_credentials)
submission_cli.add_command(clean_ftp_temp_files)
submission_cli.add_command(check_folders)
submission_cli.add_command(upload_data)
submission_cli.add_command(upload_metadata)
submission_cli.add_command(validate_submission)
# Developer-only diagnostic command. Hidden from public help and documentation.
submission_cli.add_command(validation_debug)
submission_cli.add_command(submission_templates)
submission_cli.add_command(compress_data_files)


if __name__ == "__main__":
    submission_cli()
