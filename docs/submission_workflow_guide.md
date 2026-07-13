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
    |-- check-folders
    |-- metadata-upload
    |-- data-upload
    |-- delete
    |   `-- metadata
    |-- clean-ftp-temp-files
    `-- validate
```

## End-To-End Submission Workflow

### Basic Submission Steps

Use this path when you already have valid local ISA-Tab metadata and data files.

| Step | Command | Purpose |
| --- | --- | --- |
| 1 | `mtbls auth login` | Authenticate with MetaboLights. |
| 2 | `mtbls submission create` | Create a provisional study from `study_input.json`. |
| 3 | `mtbls submission check-folders STUDY_ID --metadata-files-path PATH --data-files-path PATH -o REPORT.json` | Check local metadata and data folder prerequisites. |
| 4 | `mtbls submission metadata-upload STUDY_ID -p PATH` | Upload ISA-Tab metadata files. |
| 5 | `mtbls submission data-upload STUDY_ID --data-files-root-path PATH` | Upload data files to private FTP. |
| 6 | `mtbls submission delete metadata STUDY_ID --files FILES` | Delete selected uploaded metadata files only when they are not referenced by active study metadata. |
| 7 | `mtbls submission validate STUDY_ID --remote-validation` | Run server-side validation. |

```bash
mtbls auth login
mtbls submission create --input-file ./study_input.json -o create_response.json
mtbls submission check-folders MTBLSxxx --metadata-files-path ./MTBLSxxx --data-files-path ./MTBLSxxx/FILES -o folder_check_report.json
mtbls submission metadata-upload MTBLSxxx -p ./MTBLSxxx -o metadata_upload_response.json
mtbls submission data-upload MTBLSxxx --data-files-root-path ./MTBLSxxx/FILES -o data_upload_response.json
mtbls submission validate MTBLSxxx --remote-validation -o validation_report.json
```

Example metadata upload success output:

```json
{
  "status": "success",
  "uploaded_files": ["i_Investigation.txt", "s_MTBLSxxx.txt"],
  "skipped_files": [],
  "message": "Uploaded 2 metadata file(s) for MTBLSxxx.",
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
mtbls submission templates isa-tab-file investigation --target-path ./MTBLSxxx --override-current
mtbls submission templates isa-tab-file sample --target-path ./MTBLSxxx --override-current
mtbls submission templates isa-tab-file assay --template-name LC-MS --target-path ./MTBLSxxx --override-current
mtbls submission templates result-file --file-type maf --template-name MS --target-path ./MTBLSxxx --override-current

# 3. Create the provisional study and save the response.
mtbls submission create --input-file ./study_input.json -o create_response.json

# 4. Optional: compress Agilent .d directories before upload.
mtbls submission compress-data-files MTBLSxxx --study-path ./MTBLSxxx --update-metadata

# 5. Check local metadata and data folder prerequisites.
mtbls submission check-folders MTBLSxxx \
  --metadata-files-path ./MTBLSxxx \
  --data-files-path ./MTBLSxxx/FILES \
  -o folder_check_report.json

# 6. Upload only selected metadata files.
mtbls submission metadata-upload MTBLSxxx \
  --metadata-files-path ./MTBLSxxx \
  --selected-files i_Investigation.txt,s_MTBLSxxx.txt \
  -o metadata_upload_response.json

# 7. Clean temporary FTP artifacts from interrupted uploads, then upload data.
mtbls submission clean-ftp-temp-files MTBLSxxx -o ftp_cleanup_response.json
mtbls submission data-upload MTBLSxxx \
  --data-files-root-path ./MTBLSxxx/FILES \
  --skip-empty-folders tmp \
  -o data_upload_response.json

# 8. Validate locally first, then remotely.
mtbls submission validate MTBLSxxx \
  -p ./MTBLSxxx \
  --data-files-root-path ./MTBLSxxx/FILES \
  --validation-input-path local_validation_input.json \
  -o local_validation_report.json

mtbls submission validate MTBLSxxx \
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
| Progress bars | `data-upload` shows a `tqdm` progress bar only in interactive terminals and writes it to stderr. JSON on stdout remains clean. Disable with `--no-progress`. |
| Study IDs | Commands normalize study IDs to uppercase, for example `mtblsxxx` becomes `MTBLSxxx`. |

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

Authenticate with MetaboLights.

```bash
mtbls auth login --user user@example.org --password 'secret'
```

Or store an existing submission API JWT token:

```bash
mtbls auth login --jwt-token "$MTBLS_JWT_TOKEN"
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `--user`, `--username` | No | Option | MetaboLights username or email. If omitted, prompts interactively. |
| `--password` | No | Option | MetaboLights password. If omitted, prompts interactively. |
| `--jwt-token` | No | Option | Existing submission API JWT token. When provided, username and password are not required. |
| `--base-url` | No | Option | API base URL for this login. Defaults to saved config or production. |

Example output:

```text
Logging in with https://www.ebi.ac.uk/metabolights/ws...
Login successful.
```

#### `mtbls auth logout`

Clear the stored login session.

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

#### Download Study Creation Template

##### `mtbls submission templates study-creation-input`

Create an example `study_input.json`.

```bash
mtbls submission templates study-creation-input -o ./study_input.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `-o`, `--output` | No | Option | Output JSON path. Filename-only values are saved in the default data folder. |
| `--data-folder` | No | Option | Directory where `study_input.json` should be saved. |
| `--overwrite`, `--no-overwrite` | No | Option | Whether to overwrite an existing file. Default: `--overwrite`. |

Study creation example JSON:

```json
{
  "title": "Untargeted metabolomics analysis of example samples",
  "description": "Example study creation input for a MetaboLights provisional submission.",
  "selectedStudyCategories": ["Metabolomics"],
  "datasetLicenseAgreement": true,
  "datasetPolicyAgreement": true,
  "privacyPolicyAgreement": true,
  "publications": [],
  "relatedDatasets": [],
  "funding": [],
  "contacts": [
    {
      "firstName": "Jane",
      "lastName": "Submitter",
      "email": "jane.submitter@example.org",
      "affiliation": "Example Institute",
      "roles": ["submitter"]
    }
  ],
  "designDescriptors": [],
  "factors": [],
  "assays": [
    {
      "measurement": "metabolite profiling",
      "technology": "mass spectrometry",
      "platform": "LC-MS"
    }
  ]
}
```

#### Download ISA Metadata

##### `mtbls submission templates isa-tab-file FILE_TYPE`

Download an ISA-Tab metadata template.

```bash
mtbls submission templates isa-tab-file investigation --target-path ./MTBLSxxx
mtbls submission templates isa-tab-file sample --target-path ./MTBLSxxx
mtbls submission templates isa-tab-file assay --template-name LC-MS --target-path ./MTBLSxxx
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
mtbls submission templates result-file --file-type maf --template-name MS --target-path ./MTBLSxxx
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
    "accession": "MTBLSxxx"
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
mtbls submission metadata-upload MTBLSxxx -p ./MTBLSxxx -o metadata_upload_response.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | MetaboLights accession, for example `MTBLSxxx`. |
| `--default-submission-data-path` | No | Option | Parent folder for default metadata lookup. |
| `-p`, `--metadata-files-path`, `--metadata-path` | No | Option | Metadata folder or file. Defaults to `<default-submission-data-path>/<study-id>`. |
| `--mtbls-submission-endpoint` | No | Option | Override the configured API endpoint for this upload. |
| `--selected-files` | No | Option | Comma-separated metadata filenames to upload. |
| `-o`, `--output` | No | Option | Save upload parameters and result JSON. |

Before upload, mtblspy validates selected metadata filenames. Supported ISA-Tab upload names include `i_*.txt`, `s_<study_id>.txt`, `a_<study_id>.txt`, `a_<study_id>_*.txt`, `m_<study_id>.tsv`, and `m_<study_id>_*.tsv`. Sample, assay, and metabolite assignment filenames must match the `STUDY_ID` passed to `metadata-upload`; for example, `MTBLSxxx` accepts `s_MTBLSxxx.txt`, `a_MTBLSxxx_lc-ms.txt`, and `m_MTBLSxxx.tsv`.

#### `mtbls submission delete metadata STUDY_ID`

Delete selected uploaded ISA-Tab metadata files from an existing study. The API only deletes files that are not referenced by the active study metadata; referenced files such as active sample or assay files are rejected.

```bash
mtbls submission delete metadata MTBLSxxx --files i_Investigation.txt,s_MTBLSxxx.txt
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | MetaboLights accession, for example `MTBLSxxx`. |
| `--files` | Yes | Option | Comma-separated metadata filenames to delete. |
| `--base-url` | No | Option | MetaboLights REST API base URL used to select credentials. |

### 6. Data Preparation And Upload

#### `mtbls submission compress-data-files STUDY_ID`

Compress local Agilent `.d` directories to `.d.zip` and optionally update ISA-Tab references.

```bash
mtbls submission compress-data-files MTBLSxxx --study-path ./MTBLSxxx --update-metadata
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
mtbls submission ftp-credentials MTBLSxxx -o ftp_credentials.json
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | Study accession. |
| `-o`, `--output` | No | Option | Save FTP credentials as JSON. |

#### `mtbls submission clean-ftp-temp-files STUDY_ID`

Delete temporary FTP upload artifacts left by interrupted mtblspy data uploads. This command is intended for cleanup before retrying a data upload and does not delete normal uploaded data files.

```bash
mtbls submission clean-ftp-temp-files MTBLSxxx -o ftp_cleanup_response.json
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
  "deleted_files": ["folder1/temporary_upload_artifact.raw"],
  "message": "Deleted 1 FTP temporary file(s) for MTBLSxxx.",
  "errors": []
}
```

#### `mtbls submission data-upload STUDY_ID`

Upload local data files to the private FTP area.

```bash
mtbls submission data-upload MTBLSxxx --data-files-root-path ./MTBLSxxx/FILES -o data_upload_response.json
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
| Interrupted upload cleanup | Use `clean-ftp-temp-files` before retrying an interrupted upload. |
| Progress | Progress is item-based and shown on stderr only in interactive terminals. |

Example output:

```json
{
  "status": "success",
  "uploaded_files": ["raw/file1.raw"],
  "skipped_files": ["raw/file2.raw"],
  "missing_on_local": [],
  "message": "Uploaded 1 data file(s) or folder(s) for MTBLSxxx.",
  "errors": []
}
```

#### `mtbls submission check-folders STUDY_ID`

Check local metadata and data folders against MetaboLights submission prerequisites before upload. This command checks metadata filename formats, referenced metadata/data files, and local data file/folder standards. Use `mtbls submission validate` for ISA-Tab content completeness and rule validation.

```bash
mtbls submission check-folders MTBLSxxx \
  --metadata-files-path ./MTBLSxxx \
  --data-files-path ./MTBLSxxx/FILES
```

| Name | Required | Kind | Purpose |
| --- | --- | --- | --- |
| `STUDY_ID` | Yes | Argument | MetaboLights accession, for example `MTBLSxxx`. |
| `--default-submission-data-path` | No | Option | Parent folder for default metadata lookup. |
| `-p`, `--metadata-files-path`, `--metadata-path` | No | Option | Local ISA-Tab metadata directory. Defaults to `<default-submission-data-path>/<study-id>`. |
| `--data-files-path`, `--data-files-root-path` | No | Option | Local data `FILES` directory. Defaults to `<metadata-files-path>/FILES`. |
| `-o`, `--output` | No | Option | Override the folder check report JSON path. Without this option, the report is saved under the default study cache folder. |

The report includes errors and warnings for metadata filename issues, missing required local metadata files, metadata/data file references, accepted data folder structure, compressed raw data folder requirements, and related file/folder standards. It prints a JSON report, saves it to `~/metabolights_data/submission/cache/<study_id>/<study_id>_folder_check_report.json` by default, lets you override the path with `-o` or `--output`, and exits with status code `1` when errors are found.

Example submission folders are available under `examples/submission`. Use the valid folder to try a complete minimal study, or use the `invalid-*` folders to test validation and error handling scenarios.

To try the valid example as-is:

```bash
mtbls submission check-folders MTBLSXXX \
  --metadata-files-path examples/submission/valid/MTBLSXXX \
  --data-files-path examples/submission/valid/MTBLSXXX/FILES \
  -o folder_check_report.json
```

To adapt the example for a real provisional study:

1. Copy `examples/submission/valid/MTBLSXXX` to your working folder.
2. Rename the copied study folder from `MTBLSXXX` to your assigned study ID, for example `MTBLSxxx` or `REQxxx`.
3. Rename study-specific files so they use the same study ID: `s_<study_id>.txt`, `a_<study_id>_lc-ms.txt`, and `m_<study_id>.tsv`.
4. Update the same study ID inside `i_Investigation.txt`, the assay file reference in `i_Investigation.txt`, and the metabolite assignment file references in the assay file.
5. Replace the example sample, assay, MAF, and data-file content with your own values.
6. Run `mtbls submission check-folders` before uploading metadata or data.

### 7. Validation

#### `mtbls submission validate STUDY_ID`

Run local validation by default, or remote validation with `--remote-validation`.

Local validation:

```bash
mtbls submission validate MTBLSxxx \
  -p ./MTBLSxxx \
  --data-files-root-path ./MTBLSxxx/FILES \
  -o local_validation_report.json
```

Remote validation:

```bash
mtbls submission validate MTBLSxxx --remote-validation -o remote_validation_report.json
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
