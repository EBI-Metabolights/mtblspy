import re
from pathlib import Path
from urllib.parse import urlsplit

import click
import requests

from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_DATA_PATH
from mtblspy.commands.submissions.exceptions import SubmissionAPIError

DEFAULT_TEMPLATE_ENDPOINT = "https://www.ebi.ac.uk/metabolights/ws3"
FILE_TEMPLATE_PATH = "/public/v2/submission/file-template"


@click.command(name="isa-tab-file")
@click.argument("file_type", type=click.Choice(["assay", "sample", "investigation"]))
@click.option("--template-name", help="Template name to download.")
@click.option("--version", help="Template version to download.")
@click.option(
    "--target-path",
    type=click.Path(),
    default=str(DEFAULT_LOCAL_SUBMISSION_DATA_PATH),
    show_default=True,
    help="Directory or file path where the template will be saved.",
)
@click.option(
    "--override-current",
    is_flag=True,
    default=False,
    help="Overwrite the target file if it already exists.",
)
@click.option(
    "--mtbls-validation-endpoint",
    default=DEFAULT_TEMPLATE_ENDPOINT,
    show_default=True,
    help="MetaboLights validation API endpoint used to download templates.",
)
def isa_tab_file_template(
    file_type,
    template_name,
    version,
    target_path,
    override_current,
    mtbls_validation_endpoint,
):
    """Download an ISA-Tab metadata file template."""
    try:
        output_path = download_template_file(
            file_type=file_type,
            template_name=template_name,
            version=version,
            target_path=target_path,
            override_current=override_current,
            mtbls_validation_endpoint=mtbls_validation_endpoint,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Template file saved to {output_path}")


@click.command(name="result-file")
@click.option("--file-type", default="maf", show_default=True, help="Result template file type. Use maf for assignment.")
@click.option("--template-name", help="Template name to download, such as MS or NMR.")
@click.option("--version", help="Template version to download.")
@click.option(
    "--target-path",
    type=click.Path(),
    default=str(DEFAULT_LOCAL_SUBMISSION_DATA_PATH),
    show_default=True,
    help="Directory or file path where the template will be saved.",
)
@click.option(
    "--override-current",
    is_flag=True,
    default=False,
    help="Overwrite the target file if it already exists.",
)
@click.option(
    "--mtbls-validation-endpoint",
    default=DEFAULT_TEMPLATE_ENDPOINT,
    show_default=True,
    help="MetaboLights validation API endpoint used to download templates.",
)
def result_file_template(
    file_type,
    template_name,
    version,
    target_path,
    override_current,
    mtbls_validation_endpoint,
):
    """Download a result file template."""
    try:
        output_path = download_template_file(
            file_type=file_type,
            template_name=template_name,
            version=version,
            target_path=target_path,
            override_current=override_current,
            mtbls_validation_endpoint=mtbls_validation_endpoint,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Template file saved to {output_path}")


def download_template_file(
    file_type,
    template_name=None,
    version=None,
    target_path=DEFAULT_LOCAL_SUBMISSION_DATA_PATH,
    override_current=False,
    mtbls_validation_endpoint=DEFAULT_TEMPLATE_ENDPOINT,
):
    url = build_file_template_url(mtbls_validation_endpoint)
    params = build_file_template_params(file_type, template_name, version)
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()

    filename = get_response_filename(response) or default_template_filename(file_type, template_name)
    output_path = resolve_template_output_path(target_path, filename)
    if output_path.exists() and not override_current:
        raise SubmissionAPIError(f"Template file already exists: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path


def build_file_template_url(mtbls_validation_endpoint):
    endpoint = normalize_endpoint(mtbls_validation_endpoint)
    return f"{endpoint.rstrip('/')}{FILE_TEMPLATE_PATH}"


def build_file_template_params(file_type, template_name=None, version=None):
    params = {"file_type": file_type}
    if template_name:
        params["template_name"] = template_name
    if version:
        params["version"] = version
    return params


def normalize_endpoint(endpoint):
    endpoint = (endpoint or DEFAULT_TEMPLATE_ENDPOINT).strip().rstrip("/")
    if not endpoint:
        endpoint = DEFAULT_TEMPLATE_ENDPOINT
    if "://" not in endpoint:
        endpoint = f"https://{endpoint}"
    return endpoint


def get_response_filename(response):
    content_disposition = response.headers.get("Content-Disposition") or response.headers.get("content-disposition")
    if not content_disposition:
        return None

    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition)
    if not match:
        return None
    return Path(match.group(1)).name


def default_template_filename(file_type, template_name=None):
    suffix = default_template_suffix(file_type)
    name = template_name or file_type
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or file_type
    return f"{file_type}_{safe_name}{suffix}"


def default_template_suffix(file_type):
    if file_type == "maf":
        return ".tsv"
    if file_type in {"assay", "sample", "investigation"}:
        return ".txt"
    return ".txt"


def resolve_template_output_path(target_path, filename):
    path = Path(target_path).expanduser()
    path_text = str(target_path)
    if path.exists() and path.is_dir():
        return (path / filename).resolve()
    if path_text.endswith(("/", "\\")):
        return (path / filename).resolve()
    if has_file_suffix(path):
        return path.resolve()
    return (path / filename).resolve()


def has_file_suffix(path):
    parsed = urlsplit(str(path))
    path_text = parsed.path if parsed.scheme else str(path)
    return bool(Path(path_text).suffix)
