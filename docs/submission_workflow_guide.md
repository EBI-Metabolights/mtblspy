# MetaboLights Submission Workflow Guide

This guide shows the `mtbls` commands in the order most users need them: authenticate, configure, prepare templates, create a study, upload metadata, upload data, and validate. It also includes a full command reference with required arguments and optional switches.

## Quick Command Map

```text
mtbls
|-- auth
|   |-- login
|   `-- logout
|-- config
|   |-- set
|   `-- show
`-- submission
    |-- templates
    |   |-- study-creation-input
    |   |-- isa-tab-file
    |   `-- result-file
    |-- create
    |-- list
    |-- ftp-credentials
    |-- compress-data-files
    |-- metadata-upload
    |-- upload-data
    |-- clean-ftp-temp-files
    `-- validate
```

## Minimum Scenario

Use this path when you already have valid local ISA-Tab metadata and data files.

| Step | Command | Purpose |
| --- | --- | --- |
| 1 | `mtbls auth login` | Store MetaboLights credentials in the system keyring. |
| 2 | `mtbls submission create` | Create a provisional study from `study_input.json`. |
| 3 | `mtbls submission metadata-upload STUDY_ID -p PATH` | Upload ISA-Tab metadata files. |
| 4 | `mtbls submission upload-data STUDY_ID --data-files-root-path PATH` | Upload data files to private FTP. |
| 5 | `mtbls submission validate STUDY_ID --remote-validation` | Run server-side validation. |

```bash
mtbls auth login
mtbls submission create --input-file ./study_input.json -o create_response.json
mtbls submission metadata-upload MTBLS123 -p ./MTBLS123 -o metadata_upload_response.json
mtbls submission upload-data MTBLS123 --data-files-root-path ./MTBLS123/FILES -o data_upload_response.json
mtbls submission validate MTBLS123 --remote-validation -o validation_report.json
```

Example metadata upload success output:

```json
{
  "status": "success",
  "uploaded_files": ["i_Investigation.txt", "s_MTBLS123.txt"],
  "skipped_files": [],
  "message": "Uploaded 2 metadata file(s) for MTBLS123.",
  "errors": []
}
```

Example upload failure output:

```json
{
  "status": "failed",
  "message": "Metadata upload failed for 1 file(s).",
  "errors": [
    "i_Investigation.txt: HTTP 400 - There is no study."
  ]
}
```

## Advanced Scenario

Use this path when you want repeatable pipeline output, custom endpoints, template downloads, local validation, compression, and FTP cleanup.

```bash
# 1. Configure an endpoint once.
mtbls config set --base-url https://www.ebi.ac.uk/metabolights/ws
mtbls config show -o mtbls_config.json

# 2. Download or create starter files.
mtbls submission templates study-creation-input -o ./study_input.json
mtbls submission templates isa-tab-file investigation --target-path ./MTBLS123 --override-current
mtbls submission templates isa-tab-file sample --target-path ./MTBLS123 --override-current
mtbls submission templates isa-tab-file assay --template-name LC-MS --target-path ./MTBLS123 --override-current
mtbls submission templates result-file --file-type maf --template-name MS --target-path ./MTBLS123 --override-current

# 3. Create the provisional study and save the response.
mtbls submission create --input-file ./study_input.json -o create_response.json

# 4. Optional: compress Agilent .d directories before upload.
mtbls submission compress-data-files MTBLS123 --study-path ./MTBLS123 --update-metadata

# 5. Upload only selected metadata files.
mtbls submission metadata-upload MTBLS123 \
  --metadata-files-path ./MTBLS123 \
  --selected-files i_Investigation.txt,s_MTBLS123.txt \
  -o metadata_upload_response.json

# 6. Clean old interrupted FTP upload artifacts, then upload data.
mtbls submission clean-ftp-temp-files MTBLS123 -o ftp_cleanup_response.json
mtbls submission upload-data MTBLS123 \
  --data-files-root-path ./MTBLS123/FILES \
  --skip-empty-folders tmp \
  -o data_upload_response.json

# 7. Validate locally first, then remotely.
mtbls submission validate MTBLS123 \
  -p ./MTBLS123 \
  --data-files-root-path ./MTBLS123/FILES \
  --validation-input-path local_validation_input.json \
  -o local_validation_report.json

mtbls submission validate MTBLS123 \
  --remote-validation \
  --max-polls 180 \
  --poll-interval 10 \
  -o remote_validation_report.json
```

## Output And Pipeline Notes

| Behavior | Detail |
| --- | --- |
| JSON output | Commands that return JSON print JSON to stdout. Use `-o/--output` to save it as a file. |
| Filename-only `-o` | Saved under the command's default cache/data folder. Use `./path/file.json` or an absolute path to control location. |
| Failure output | Upload commands return the same JSON structure on success and failure: `status`, `message`, `errors`, and command-specific file lists. |
| Progress bars | `upload-data` shows a `tqdm` progress bar only in interactive terminals and writes it to stderr. JSON on stdout remains clean. Disable with `--no-progress`. |
| Study IDs | Commands normalize study IDs to uppercase, for example `mtbls123` becomes `MTBLS123`. |

## Workflow Reference

### Top-Level CLI

#### `mtbls`

```bash
mtbls --help
mtbls --version
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--version` | No | Option | Print the installed `mtblspy` version. |
| `-h`, `--help` | No | Option | Show help for any command or subcommand. |

#### Command groups

| Group | Purpose |
| --- | --- |
| `mtbls auth` | Login and logout commands. |
| `mtbls config` | Persistent runtime configuration commands. |
| `mtbls submission` | Study creation, templates, upload, FTP, validation, and debugging commands. |
| `mtbls submission templates` | Template download and sample input helpers. |

### 1. Authentication

#### `mtbls auth login`

Store credentials and tokens in the system keyring.

```bash
mtbls auth login --user user@example.org --password 'secret'
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--user`, `--username` | No | Option | MetaboLights username or email. If omitted, prompts interactively. Can use `MTBLS_USER`. |
| `--password` | No | Option | MetaboLights password. If omitted, prompts interactively. Can use `MTBLS_PASSWORD`. |
| `--base-url` | No | Option | API base URL for this login. Defaults to config, environment, or production. |

Example output:

```text
Logging in with https://www.ebi.ac.uk/metabolights/ws...
Login successful. Tokens and user saved to system keyring.
```

#### `mtbls auth logout`

Clear stored credentials from the system keyring.

```bash
mtbls auth logout
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--base-url` | No | Option | API base URL whose stored session should be cleared. |

### 2. Configuration

#### `mtbls config set`

Save a default MetaboLights REST API base URL.

```bash
mtbls config set --base-url https://www.ebi.ac.uk/metabolights/ws
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--base-url` | Yes | Option | Base URL saved for later commands. |

#### `mtbls config show`

Show the effective configuration.

```bash
mtbls config show
mtbls config show -o mtbls_config.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `-o`, `--output` | No | Option | Save configuration JSON to a file. |

Example output:

```json
{
  "base_url": "https://www.ebi.ac.uk/metabolights/ws"
}
```

### 3. Submission Templates

Templates help you start with valid study creation JSON and ISA-Tab files.

#### `mtbls submission templates study-creation-input`

Create an example `study_input.json`.

```bash
mtbls submission templates study-creation-input -o ./study_input.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `-o`, `--output` | No | Option | Output JSON path. Filename-only values are saved in the default data folder. |
| `--data-folder` | No | Option | Directory where `study_input.json` should be saved. |
| `--overwrite`, `--no-overwrite` | No | Option | Whether to overwrite an existing file. Default: `--overwrite`. |

#### `mtbls submission templates isa-tab-file FILE_TYPE`

Download an ISA-Tab metadata template.

```bash
mtbls submission templates isa-tab-file assay --template-name LC-MS --target-path ./MTBLS123
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `FILE_TYPE` | Yes | Argument | One of `investigation`, `sample`, or `assay`. |
| `--template-name` | No | Option | Template name, for example `LC-MS`, `GC-MS`, or `NMR`. |
| `--version` | No | Option | Template version. |
| `--target-path` | No | Option | Directory or file path for the downloaded template. |
| `--override-current` | No | Flag | Overwrite the target file if it already exists. |
| `--mtbls-validation-endpoint` | No | Option | Validation API endpoint used to download templates. |

#### `mtbls submission templates result-file`

Download a result file template, usually a MAF assignment file.

```bash
mtbls submission templates result-file --file-type maf --template-name MS --target-path ./MTBLS123
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--file-type` | No | Option | Result template type. Default: `maf`. |
| `--template-name` | No | Option | Template name, for example `MS` or `NMR`. |
| `--version` | No | Option | Template version. |
| `--target-path` | No | Option | Directory or file path for the downloaded template. |
| `--override-current` | No | Flag | Overwrite the target file if it already exists. |
| `--mtbls-validation-endpoint` | No | Option | Validation API endpoint used to download templates. |

### 4. Study Creation

#### `mtbls submission create`

Create a provisional study from a JSON study creation request.

```bash
mtbls submission create --input-file ./study_input.json -o create_response.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--input-file` | No | Option | Study creation input JSON. Default: `~/metabolights_data/submission/data/study_input.json`. |
| `--input-format` | No | Option | Input format. Currently `json`. |
| `-o`, `--output` | No | Option | Save the creation response as JSON. |

Example output:

```json
{
  "content": {
    "accession": "MTBLS123"
  },
  "message": "Study created successfully"
}
```

#### `mtbls submission list`

List studies created by the authenticated user.

```bash
mtbls submission list
mtbls submission list -o studies.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `-o`, `--output` | No | Option | Save the studies list as JSON. |

### 5. Metadata Upload

#### `mtbls submission metadata-upload STUDY_ID`

Upload ISA-Tab metadata files to an existing provisional study.

```bash
mtbls submission metadata-upload MTBLS123 -p ./MTBLS123 -o metadata_upload_response.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | MetaboLights accession, for example `MTBLS123`. |
| `--default-submission-data-path` | No | Option | Parent folder for default metadata lookup. |
| `-p`, `--metadata-files-path`, `--metadata-path` | No | Option | Metadata folder or file. Defaults to `<default-submission-data-path>/<study-id>`. |
| `--mtbls-submission-endpoint` | No | Option | Override the configured API endpoint for this upload. |
| `--selected-files` | No | Option | Comma-separated metadata filenames to upload. |
| `-o`, `--output` | No | Option | Save upload parameters and result JSON. |

Supported ISA-Tab metadata names include `i_*.txt`, `s_*.txt`, `a_*.txt`, and `m_*.tsv`.

### 6. Data Preparation And Upload

#### `mtbls submission compress-data-files STUDY_ID`

Compress local Agilent `.d` directories to `.d.zip` and optionally update ISA-Tab references.

```bash
mtbls submission compress-data-files MTBLS123 --study-path ./MTBLS123 --update-metadata
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | Study accession. |
| `-p`, `--study-path` | No | Option | Local study directory. Default: `~/metabolights_data/submission/data/<study-id>`. |
| `--files-path` | No | Option | Local data `FILES` directory. Default: `<study-path>/FILES`. |
| `--metadata-path` | No | Option | Local metadata directory. Default: `<study-path>`. |
| `--overwrite`, `--no-overwrite` | No | Option | Overwrite existing `.d.zip` files. Default: `--no-overwrite`. |
| `--update-metadata`, `--no-update-metadata` | No | Option | Update metadata references from `.d` to `.d.zip`. Default: `--update-metadata`. |
| `--remove-original` | No | Flag | Remove original `.d` directories after compression. |

#### `mtbls submission ftp-credentials STUDY_ID`

Show private FTP upload credentials for a study.

```bash
mtbls submission ftp-credentials MTBLS123 -o ftp_credentials.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | Study accession. |
| `-o`, `--output` | No | Option | Save FTP credentials as JSON. |

#### `mtbls submission clean-ftp-temp-files STUDY_ID`

Delete incomplete FTP temporary files whose filename starts with `.ftp_` under the study FTP folder.

```bash
mtbls submission clean-ftp-temp-files MTBLS123 -o ftp_cleanup_response.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | Study accession. |
| `--mtbls-submission-endpoint` | No | Option | Override the API endpoint used to fetch FTP credentials. |
| `-o`, `--output` | No | Option | Save cleanup parameters and result JSON. |

Example output:

```json
{
  "status": "success",
  "deleted_files": ["folder1/.ftp_interrupted.raw"],
  "message": "Deleted 1 FTP temporary file(s) for MTBLS123.",
  "errors": []
}
```

#### `mtbls submission upload-data STUDY_ID`

Upload local data files to the private FTP area.

```bash
mtbls submission upload-data MTBLS123 --data-files-root-path ./MTBLS123/FILES -o data_upload_response.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | Study accession. |
| `--data-files-root-path` | Yes | Option | Local root directory containing files to upload. |
| `--selected-files` | No | Option | Comma-separated files or folders under the root to upload. Default: all files. |
| `--skip-uploaded-files` | No | Option | Comma-separated files or folders under the root to skip. |
| `--skip-empty-folders` | No | Option | Comma-separated empty folders under the root to skip. |
| `--mtbls-submission-endpoint` | No | Option | Override the configured API endpoint for this upload. |
| `-o`, `--output` | No | Option | Save upload parameters and result JSON. |
| `--progress`, `--no-progress` | No | Option | Show or disable the interactive upload progress bar. Default: `--progress`. |

Data upload notes:

| Behavior | Detail |
| --- | --- |
| Existing remote file | Skipped when the remote path and file size match the local file. |
| Temporary upload name | Files are uploaded as `.ftp_<filename>` first, then renamed after transfer. |
| Size verification | If the FTP server reports temp file size and it differs from local size, upload fails and the temp file is deleted. |
| Progress | Progress is item-based and shown on stderr only in interactive terminals. |

Example output:

```json
{
  "status": "success",
  "uploaded_files": ["raw/file1.raw"],
  "skipped_files": ["raw/file2.raw"],
  "missing_on_local": [],
  "message": "Uploaded 1 data file(s) or folder(s) for MTBLS123.",
  "errors": []
}
```

### 7. Validation

#### `mtbls submission validate STUDY_ID`

Run local validation by default, or remote validation with `--remote-validation`.

Local validation:

```bash
mtbls submission validate MTBLS123 \
  -p ./MTBLS123 \
  --data-files-root-path ./MTBLS123/FILES \
  -o local_validation_report.json
```

Remote validation:

```bash
mtbls submission validate MTBLS123 --remote-validation -o remote_validation_report.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | Study accession. |
| `--default-submission-data-path` | No | Option | Parent folder for default local metadata lookup. |
| `-p`, `--metadata-files-path`, `--metadata-path` | No | Option | Local ISA-Tab metadata directory. |
| `--data-files-root-path` | Local only | Option | Local data root for local validation. Not required for `--remote-validation`. |
| `--remote-validation` | No | Flag | Run validation through the remote submission API. |
| `--mtbls-validation-wasm-path` | No | Option | Local standalone WASM or OPA WASM validation bundle path. |
| `--mtbls-validation-wasm-url` | No | Option | URL to download validation WASM when missing. |
| `--mtbls-validation-endpoint` | No | Option | Validation API endpoint for remote validation. |
| `--mtbls-submission-endpoint` | No | Option | Submission API endpoint for remote validation. |
| `--validation-bundle-path`, `--mtbls-validation-bundle-path` | No | Option | Local OPA validation bundle path. |
| `--validation-bundle-url`, `--mtbls-validation-bundle-url` | No | Option | URL to download the OPA validation bundle. |
| `--refetch-validation-bundle` | No | Flag | Download the bundle even if the local file exists. |
| `--opa-executable-path` | No | Option | OPA executable path. Default: `opa`. |
| `--validation-input-path` | No | Option | Save generated local validation input JSON. |
| `--config-file` | No | Option | Validation override configuration file. |
| `--overridden-rules-file-path` | No | Option | Text file of rule IDs or metadata filenames to ignore. |
| `--max-polls` | Remote only | Option | Maximum remote validation status checks. |
| `--poll-interval` | Remote only | Option | Seconds between remote validation polls. |
| `-o`, `-v`, `--output`, `--validation-file-path`, `--validation_file_path` | No | Option | Save validation report JSON. |
| `--output-format` | No | Option | Output format. Currently `json`. |

## Recommended Pipeline Pattern

Use explicit file paths and save every JSON response.

```bash
set -e

STUDY_ID="MTBLS123"
STUDY_DIR="./${STUDY_ID}"

mtbls config set --base-url https://www.ebi.ac.uk/metabolights/ws
mtbls auth login --user "$MTBLS_USER" --password "$MTBLS_PASSWORD"

mtbls submission metadata-upload "$STUDY_ID" \
  -p "$STUDY_DIR" \
  -o "./reports/metadata_upload.json"

mtbls submission clean-ftp-temp-files "$STUDY_ID" \
  -o "./reports/ftp_cleanup.json"

mtbls submission upload-data "$STUDY_ID" \
  --data-files-root-path "$STUDY_DIR/FILES" \
  --no-progress \
  -o "./reports/data_upload.json"

mtbls submission validate "$STUDY_ID" \
  --remote-validation \
  -o "./reports/remote_validation.json"
```

In automation, parse `status` and `errors` from each saved JSON file before moving to the next step.
