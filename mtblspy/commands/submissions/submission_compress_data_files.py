import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import click

from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_DATA_PATH
from mtblspy.commands.submissions.exceptions import SubmissionAPIError


@dataclass
class DataFilesCompressionResult:
    study_id: str
    files_path: Path
    compressed_files: list[Path]
    skipped_files: list[Path]
    updated_metadata_files: list[Path]
    removed_directories: list[Path]


@click.command(name="compress-data-files")
@click.argument("study_id")
@click.option(
    "--study-path",
    "-p",
    type=click.Path(exists=False, file_okay=False),
    help="Local study directory. Defaults to ~/metabolights_data/submission/data/<study_id>.",
)
@click.option(
    "--files-path",
    type=click.Path(exists=False, file_okay=False),
    help="Local data FILES directory. Defaults to <study-path>/FILES.",
)
@click.option(
    "--metadata-path",
    type=click.Path(exists=False, file_okay=False),
    help="Local ISA-Tab metadata directory. Defaults to <study-path>.",
)
@click.option(
    "--overwrite/--no-overwrite",
    default=False,
    show_default=True,
    help="Overwrite existing .d.zip files.",
)
@click.option(
    "--update-metadata/--no-update-metadata",
    default=True,
    show_default=True,
    help="Update ISA-Tab metadata references from .d to .d.zip.",
)
@click.option(
    "--remove-original",
    is_flag=True,
    default=False,
    help="Remove each .d directory after its .d.zip file is created.",
)
def compress_data_files(
    study_id,
    study_path,
    files_path,
    metadata_path,
    overwrite,
    update_metadata,
    remove_original,
):
    """Compress local .d data directories to .d.zip files."""
    try:
        result = compress_study_data_files(
            study_id,
            study_path=study_path,
            files_path=files_path,
            metadata_path=metadata_path,
            overwrite=overwrite,
            update_metadata=update_metadata,
            remove_original=remove_original,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    compressed_count = len(result.compressed_files)
    click.echo(
        f"Compressed {compressed_count} .d "
        f"{pluralize(compressed_count, 'directory', 'directories')} for {result.study_id}."
    )
    for file_path in result.compressed_files:
        click.echo(f"- {file_path}")
    if result.skipped_files:
        click.echo(f"Skipped {len(result.skipped_files)} existing .d.zip file(s).")
    if result.updated_metadata_files:
        click.echo(f"Updated {len(result.updated_metadata_files)} metadata file(s).")
    if result.removed_directories:
        removed_count = len(result.removed_directories)
        click.echo(
            f"Removed {removed_count} original .d "
            f"{pluralize(removed_count, 'directory', 'directories')}."
        )


def compress_study_data_files(
    study_id,
    study_path=None,
    files_path=None,
    metadata_path=None,
    overwrite=False,
    update_metadata=True,
    remove_original=False,
):
    study_id = study_id.upper().strip()
    study_root = resolve_study_path(study_id, study_path)
    files_root = resolve_files_path(study_root, files_path)
    metadata_root = resolve_metadata_path(study_root, metadata_path)

    if not files_root.exists():
        raise SubmissionAPIError(f"Data FILES path does not exist: {files_root}")
    if not files_root.is_dir():
        raise SubmissionAPIError(f"Data FILES path is not a directory: {files_root}")
    if update_metadata and (not metadata_root.exists() or not metadata_root.is_dir()):
        raise SubmissionAPIError(
            f"Metadata path does not exist or is not a directory: {metadata_root}"
        )

    compressed_files: list[Path] = []
    skipped_files: list[Path] = []
    removed_directories: list[Path] = []
    compressed_directories = find_dot_d_directories(files_root)

    for directory in compressed_directories:
        zip_path = directory.with_name(f"{directory.name}.zip")
        if zip_path.exists() and not overwrite:
            skipped_files.append(zip_path)
            continue
        zip_dot_d_directory(directory, zip_path)
        compressed_files.append(zip_path)
        if remove_original:
            shutil.rmtree(directory)
            removed_directories.append(directory)

    updated_metadata_files: list[Path] = []
    if update_metadata and compressed_files:
        updated_metadata_files = update_metadata_dot_d_references(
            metadata_root,
            files_root,
            [path.with_suffix("") for path in compressed_files],
        )

    return DataFilesCompressionResult(
        study_id=study_id,
        files_path=files_root,
        compressed_files=compressed_files,
        skipped_files=skipped_files,
        updated_metadata_files=updated_metadata_files,
        removed_directories=removed_directories,
    )


def resolve_study_path(study_id, study_path=None):
    if study_path:
        return Path(study_path).expanduser().resolve()
    return (DEFAULT_LOCAL_SUBMISSION_DATA_PATH / study_id).expanduser().resolve()


def resolve_files_path(study_root, files_path=None):
    if not files_path:
        return (study_root / "FILES").resolve()
    path = Path(files_path).expanduser()
    if not path.is_absolute():
        path = study_root / path
    return path.resolve()


def resolve_metadata_path(study_root, metadata_path=None):
    if not metadata_path:
        return study_root.resolve()
    path = Path(metadata_path).expanduser()
    if not path.is_absolute():
        path = study_root / path
    return path.resolve()


def find_dot_d_directories(files_root):
    directories: list[Path] = []
    for root, dirnames, _filenames in Path(files_root).walk():
        dot_d_names = [name for name in dirnames if name.lower().endswith(".d")]
        directories.extend((root / name).resolve() for name in dot_d_names)
        dirnames[:] = [name for name in dirnames if not name.lower().endswith(".d")]
    return sorted(directories)


def zip_dot_d_directory(directory, zip_path):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            archive.write(path, path.relative_to(directory.parent))


def update_metadata_dot_d_references(metadata_root, files_root, dot_d_directories):
    replacements = dict(build_metadata_replacements(files_root, dot_d_directories))
    updated_files: list[Path] = []

    for metadata_file in sorted(metadata_root.iterdir()):
        if not metadata_file.is_file() or not is_metadata_filename(metadata_file.name):
            continue
        original_text = metadata_file.read_text(encoding="utf-8")
        updated_text = update_tsv_cells(original_text, replacements)
        if updated_text != original_text:
            metadata_file.write_text(updated_text, encoding="utf-8")
            updated_files.append(metadata_file)

    return updated_files


def build_metadata_replacements(files_root, dot_d_directories):
    replacements: list[tuple[str, str]] = []
    for directory in dot_d_directories:
        relative_path = directory.relative_to(files_root).as_posix()
        zip_relative_path = f"{relative_path}.zip"
        replacements.append((f"FILES/{relative_path}", f"FILES/{zip_relative_path}"))
        replacements.append((relative_path, zip_relative_path))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    return replacements


def is_metadata_filename(filename):
    return (
        filename.startswith(("a_", "s_", "i_")) and filename.endswith(".txt")
    ) or (filename.startswith("m_") and filename.endswith(".tsv"))


def update_tsv_cells(text, replacements):
    updated_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        body, line_ending = split_line_ending(line)
        fields = body.split("\t")
        updated_fields = [replacements.get(field, field) for field in fields]
        updated_lines.append("\t".join(updated_fields) + line_ending)
    return "".join(updated_lines)


def split_line_ending(line):
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1]
    return line, ""


def pluralize(count, singular, plural):
    return singular if count == 1 else plural
