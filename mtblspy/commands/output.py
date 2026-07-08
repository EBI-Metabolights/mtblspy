import json
from pathlib import Path

import click


def json_output_option(help_text):
    return click.option(
        "--output",
        "-o",
        type=click.Path(),
        help=help_text,
    )


def resolve_json_output_path(output_path, default_directory, default_filename):
    default_directory = Path(default_directory).expanduser()
    if not output_path:
        return (default_directory / default_filename).resolve()

    path = Path(output_path).expanduser()
    path_text = str(output_path)
    if path.exists() and path.is_dir():
        return (path / default_filename).resolve()
    if path_text.endswith(("/", "\\")):
        return (path / default_filename).resolve()
    return path.resolve()


def write_json_file(data, output_path):
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists() and output_path.is_dir():
        raise ValueError(f"JSON output path is a directory: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, indent=2, default=str)
        output_file.write("\n")
    return output_path


def save_json_output(data, output_path, default_directory, default_filename):
    resolved_path = resolve_json_output_path(output_path, default_directory, default_filename)
    return write_json_file(data, resolved_path)
