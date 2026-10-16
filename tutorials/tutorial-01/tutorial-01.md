# ELIXIR Metabolomics Community Meeting 2026 tutorial

This tutorial uses `mtblspy` to submit a small example metabolomics study to the [MetaboLights test server](https://wwwdev.ebi.ac.uk/metabolights/). Run the commands from the repository root. Replace `MTBLSxxx` in the commands with the accession returned when you create your study.

The workflow is:

1. Create a MetaboLights test account.
2. Install `mtblspy`.
3. Configure and authenticate the command-line tool.
4. Create and list a provisional study.
5. Download ISA-Tab templates and prepare the example files.
6. Check the local folder structure.
7. Upload metadata and data.
8. Run remote validation.

## 1. Create a MetaboLights test account

1. Open the [MetaboLights test editor](https://wwwdev.ebi.ac.uk/metabolights/editor) and create an account.
2. Confirm the account using the link in the confirmation email.
3. Sign in once in the web editor to confirm that the account works.

## 2. Install `mtblspy`

You need [Git](https://git-scm.com/install) and the [uv package manager](https://docs.astral.sh/uv/).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git --version
uv --version
```

Clone the repository and create its Python environment:

```bash
mkdir -p ~/tutorials/mtblspy-tutorials
cd ~/tutorials/mtblspy-tutorials
git clone https://github.com/EBI-Metabolights/mtblspy.git
cd mtblspy

uv sync
source .venv/bin/activate
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Confirm that the command is installed:

```bash
mtbls --version
mtbls --help
```

## 3. Configure the test server and log in

Save the test REST API URL so that later commands use the correct server:

```bash
mtbls config set --base-url https://wwwdev.ebi.ac.uk/metabolights/ws
mtbls config show
```

Log in interactively. Enter the email address and password for your test account when prompted. The password is hidden while you type.

```bash
mtbls auth login
```

A successful login prints `Login successful.` and stores the credentials for later commands. You do not need to put your password in the command or in this tutorial.

## 4. Create and list a study

Generate a study-creation example:

```bash
mtbls submission templates study-creation-input \
  --output tutorials/tutorial-01/study_input.json
```

Open `tutorials/tutorial-01/study_input.json` and replace the example title, description, contact details, and study category with values suitable for this exercise. Then create the provisional study:

```bash
mtbls submission create \
  --input-file tutorials/tutorial-01/study_input.json \
  --output tutorials/tutorial-01/create_response.json
```

The response contains a new accession such as `REQxxxxx`. Use your returned accession everywhere this tutorial shows `MTBLSxxx`. Confirm that the study belongs to your account:

```bash
mtbls submission list
```

For convenience, set a shell variable now:

```bash
export STUDY_ID=REQxxx
```

## 5. Download and prepare the metadata templates

The investigation, sample, assay, and metabolite-assignment (MAF) templates must describe the same study category. This example uses LC-MS and the MS assignment template. Download all four into `test-data`:

```bash
mtbls submission templates isa-tab-file investigation \
  --target-path tutorials/tutorial-01/test-data/i_Investigation.txt \
  --override-current

mtbls submission templates isa-tab-file sample \
  --target-path "tutorials/tutorial-01/test-data/s_${STUDY_ID}.txt" \
  --override-current

mtbls submission templates isa-tab-file assay \
  --template-name LC-MS \
  --target-path "tutorials/tutorial-01/test-data/a_${STUDY_ID}_lc-ms.txt" \
  --override-current

mtbls submission templates result-file \
  --file-type maf \
  --template-name MS \
  --target-path "tutorials/tutorial-01/test-data/m_${STUDY_ID}.tsv" \
  --override-current
```

Edit the downloaded files and replace their example values with the tutorial study values. In particular:

- Put `$STUDY_ID` in the investigation and study identifier fields.
- In `i_Investigation.txt`, reference `s_${STUDY_ID}.txt` and `a_${STUDY_ID}_lc-ms.txt`.
- In the assay file, reference `m_${STUDY_ID}.tsv` and the data file as `FILES/RAW_FILES/data01.raw`.
- Keep the supplied example data file at `test-data/FILES/RAW_FILES/data01.raw`.

Your local directory should now look like this:

```text
tutorials/tutorial-01/test-data/
├── i_Investigation.txt
├── s_MTBLSxxx.txt
├── a_MTBLSxxx_lc-ms.txt
├── m_MTBLSxxx.tsv
└── FILES/
    └── RAW_FILES/
        └── data01.raw
```

The `MTBLSxxx` part above represents your actual accession.

## 6. Check the local folders

`check-folders` checks that the metadata files are in the metadata directory, that data is under `FILES`, and that metadata references point to files that exist. The optional `--study-id` check also confirms that the sample, assay, and MAF filenames contain your accession.

```bash
mtbls submission check-folders \
  --study-id "$STUDY_ID" \
  --metadata-files-path tutorials/tutorial-01/test-data \
  --output tutorials/tutorial-01/folder_check_report.json
```

The data path defaults to `FILES` under the metadata directory. You can omit `--study-id` when an accession has not been assigned yet; the remaining local structure and reference checks still run. Fix every item in `errors` before continuing. Warnings should also be reviewed.

## 7. Upload metadata and data

Upload the four ISA-Tab metadata files:

```bash
mtbls submission metadata-upload "$STUDY_ID" \
  --metadata-files-path tutorials/tutorial-01/test-data \
  --output tutorials/tutorial-01/metadata_upload_response.json
```

Then upload the contents of `FILES` to the study's private FTP area:

```bash
mtbls submission data-upload "$STUDY_ID" \
  --data-files-root-path tutorials/tutorial-01/test-data/FILES \
  --output tutorials/tutorial-01/data_upload_response.json
```

## 8. Run remote validation

Run validation on the uploaded server copy:

```bash
mtbls submission validate "$STUDY_ID" \
  --remote-validation \
  --output tutorials/tutorial-01/validation_report.json
```

Open `tutorials/tutorial-01/validation_report.json`. A successful result has no validation errors. If the report contains errors, correct the local metadata, repeat the folder check, upload the changed metadata, and run remote validation again.

`mtblspy` also supports local validation, but it requires an additional local validation bundle and OPA setup. That advanced setup is intentionally outside this introductory tutorial; `mtbls submission validate --help` lists the available local-validation options.
