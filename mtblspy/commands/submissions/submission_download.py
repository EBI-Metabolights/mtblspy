import json
from pathlib import Path

import click
from tqdm import tqdm

from mtblspy.commands.submissions.cli_utils import create_submission_client, get_submission_client, jwt_token_option
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.group(name="download")
@click.argument("study_id")
@click.pass_context
def download_submission(ctx, study_id):
    """Download study metadata or data files."""
    ctx.ensure_object(dict)
    ctx.obj["study_id"] = study_id


@download_submission.command(name="metadata")
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--files",
    "selected_files",
    help="Comma-separated metadata filenames to download. Defaults to all ISA-Tab and result metadata files.",
)
@click.option(
    "--target-path",
    "--output",
    "-o",
    "target_path",
    type=click.Path(file_okay=False),
    help="Directory to save metadata files. Defaults to the local MetaboLights data folder.",
)
@jwt_token_option
@click.pass_context
def download_metadata(ctx, base_url, selected_files, target_path, jwt_token):
    """Download ISA-Tab metadata files and result files."""
    study_id = ctx.obj["study_id"]
    try:
        client = get_submission_client(ctx, base_url=base_url, jwt_token=jwt_token, factory=create_submission_client)
        result = client.download_metadata_files(
            study_id,
            target_path=target_path,
            selected_files=selected_files,
        )
    except SubmissionError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(json.dumps(download_result_payload(result), indent=2))


@download_submission.command(name="data")
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--files",
    "selected_files",
    help="Comma-separated data files or folders to download.",
)
@click.option(
    "--all",
    "download_all",
    is_flag=True,
    help="Download all data files. Use with care because study data files can be large.",
)
@click.option(
    "--target-path",
    "--output",
    "-o",
    "target_path",
    type=click.Path(file_okay=False),
    help="Directory to save data files. Defaults to the local MetaboLights data folder.",
)
@click.option(
    "--progress/--no-progress",
    default=True,
    show_default=True,
    help="Show an interactive progress bar on stderr while downloading.",
)
@jwt_token_option
@click.pass_context
def download_data(ctx, base_url, selected_files, download_all, target_path, progress, jwt_token):
    """Download study data files from the private FTP area."""
    study_id = ctx.obj["study_id"]
    progress_bar = DataDownloadProgress(enabled=progress and is_progress_stream_interactive())
    try:
        if selected_files and download_all:
            raise click.ClickException("Use either --files or --all, not both.")
        if not selected_files and not download_all:
            raise click.ClickException(
                "Data download requires --files because study data files can be large. "
                "Use --files with comma-separated file or folder names, or pass --all to download all data files."
            )
        client = get_submission_client(ctx, base_url=base_url, jwt_token=jwt_token, factory=create_submission_client)
        download_kwargs = {
            "target_path": target_path,
            "selected_files": selected_files,
            "download_all": download_all,
        }
        if progress_bar.enabled:
            download_kwargs["progress_callback"] = progress_bar.callback
        result = client.download_data_files(
            study_id,
            **download_kwargs,
        )
    except click.ClickException:
        raise
    except SubmissionError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        progress_bar.close()

    click.echo(json.dumps(download_result_payload(result), indent=2))


def download_result_payload(result):
    return {
        "study_id": result.study_id,
        "status": "failed" if result.errors or result.missing_files else "success",
        "downloaded_files": [str(Path(path)) for path in result.downloaded_files],
        "skipped_files": result.skipped_files,
        "missing_files": result.missing_files,
        "message": build_download_message(result),
        "errors": result.errors,
    }


def build_download_message(result):
    file_count = len(result.downloaded_files)
    parts = [f"Downloaded {file_count} file(s) for {result.study_id}."]
    if result.missing_files:
        parts.append(f"Missing {len(result.missing_files)} requested file(s): " + ", ".join(result.missing_files))
    if result.errors:
        parts.append(f"Encountered {len(result.errors)} error(s).")
    return " ".join(parts)


def is_progress_stream_interactive():
    return click.get_text_stream("stderr").isatty()


class DataDownloadProgress:
    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self.progress_bar = None

    def callback(self, event):
        if not self.enabled:
            return
        event_name = event.get("event")
        if event_name == "start":
            self.start(event.get("total", 0))
        elif event_name == "item":
            self.update(event.get("path", ""), event.get("status", "done"))

    def start(self, total):
        if self.progress_bar is not None:
            return
        stream = click.get_text_stream("stderr")
        self.progress_bar = tqdm(
            total=total,
            desc="Downloading data",
            unit="item",
            file=stream,
            disable=not stream.isatty(),
        )

    def update(self, path, status):
        if self.progress_bar is None:
            self.start(0)
        if self.progress_bar.disable:
            return
        self.progress_bar.set_postfix_str(format_progress_item(path, status), refresh=False)
        self.progress_bar.update(1)

    def close(self):
        if self.progress_bar is not None:
            self.progress_bar.close()
            self.progress_bar = None


def format_progress_item(path, status):
    path = str(path)
    if len(path) > 48:
        path = f"...{path[-45:]}"
    return f"{status}: {path}"
