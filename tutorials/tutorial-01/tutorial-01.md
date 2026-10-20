# ELIXIR Metabolomics Community Meeting 2026 tutorial

This tutorial uses `mtblspy` to submit a small example metabolomics study to the [MetaboLights test server](https://wwwdev.ebi.ac.uk/metabolights/). Run the commands from the repository root. Replace `REQxxx` in the commands with the accession returned when you create your study.

The workflow is:

1. Create a MetaboLights test account.
2. Install `mtblspy`.
3. Configure and authenticate the command-line tool.
4. Create and list a provisional study.
5. Download the study investigation, download the remaining templates, and prepare the example files.
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

The response contains a new accession such as `REQxxxxx`. Use your returned accession everywhere this tutorial shows `REQxxx`. Confirm that the study belongs to your account:

```bash
mtbls submission list
```

As an additional confirmation, open the [MetaboLights test editor](https://wwwdev.ebi.ac.uk/metabolights/editor), sign in, and check that the newly created study and its accession appear in your study list. Open the study once to confirm that you can access it before continuing.

For convenience, set a shell variable now:

```bash
export STUDY_ID=REQxxx
```

## 5. Download and prepare the metadata

The provisional study already has an investigation file containing its accession and the details supplied during study creation. Download that existing file into `test-data` instead of replacing it with a blank investigation template. `--target-path` is a directory; the command keeps the server filename `i_Investigation.txt`:

```bash
mtbls submission download "$STUDY_ID" metadata \
  --files i_Investigation.txt \
  --target-path tutorials/tutorial-01/test-data
```

If the study already contains other metadata that you want to edit locally, omit `--files` to download all metadata currently available for the study:

```bash
mtbls submission download "$STUDY_ID" metadata \
  --target-path tutorials/tutorial-01/test-data
```

For this newly created study, download the sample, assay, and metabolite-assignment (MAF) templates separately. The files must describe the same study category; this example uses LC-MS and the MS assignment template:

```bash
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

### Add the LC-MS assay to the investigation file

Open `tutorials/tutorial-01/test-data/i_Investigation.txt`. In its `STUDY ASSAYS` section, add or update the following rows so the investigation file registers the assay file and its LC-MS details. Keep the tab-separated format used by the template:

```text
STUDY ASSAYS
Study Assay File Name	a_${STUDY_ID}_lc-ms.txt
Study Assay Measurement Type	metabolite profiling
Study Assay Technology Type	mass spectrometry
Study Assay Technology Platform	LC-MS
```

If the template already includes these rows, update their values rather than adding duplicate rows. For more than one assay, add a further tab-separated value in each applicable row, in the same column position as its assay filename.

Review the downloaded investigation file, then complete the sample, assay, and MAF sheets with the appropriate details for your experiment; do not leave the downloaded example rows and values unchanged. In particular:

- Confirm that `$STUDY_ID` appears in the investigation and study identifier fields.
- In `i_Investigation.txt`, reference `s_${STUDY_ID}.txt` and `a_${STUDY_ID}_lc-ms.txt`.
- In the sample sheet, add the study samples and their sample characteristics.
- In the assay sheet, complete the assay rows and use the `Raw Spectral Data File` column to reference `FILES/RAW_FILES/data01.raw`. This removes the `data_files_not_referenced` warning.
- In the assay sheet, use the `Metabolite Assignment File` column to reference `m_${STUDY_ID}.tsv`. This removes the `assignment_files_not_referenced` warning.
- In the MAF sheet, add the metabolite-assignment results for the assay data.
- Keep the supplied example data file at `test-data/FILES/RAW_FILES/data01.raw`.

Your local directory should now look like this:

```text
tutorials/tutorial-01/test-data/
├── i_Investigation.txt
├── s_REQxxx.txt
├── a_REQxxx_lc-ms.txt
├── m_REQxxx.tsv
└── FILES/
    └── RAW_FILES/
        └── data01.raw
```

The `REQxxx` part above represents your actual accession.

## 6. Check the local folders

`check-folders` checks that the metadata files are in the metadata directory, that data is under `FILES`, and that metadata references point to files that exist. The optional `--study-id` check also confirms that the sample, assay, and MAF filenames contain your accession.

```bash
mtbls submission check-folders \
  --study-id "$STUDY_ID" \
  --metadata-files-path tutorials/tutorial-01/test-data \
  --output tutorials/tutorial-01/folder_check_report.json
```

The data path defaults to `FILES` under the metadata directory. You can omit `--study-id` when an accession has not been assigned yet; the remaining local structure and reference checks still run. Fix every item in `errors` before continuing. Also resolve the `data_files_not_referenced` and `assignment_files_not_referenced` warnings by completing the assay-sheet references above.

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

Use `--sync-data-files` to index the uploaded private FTP data before validation. The command waits for indexing to finish and starts remote validation only after it succeeds:

```bash
mtbls submission validate "$STUDY_ID" \
  --remote-validation \
  --sync-data-files \
  --output tutorials/tutorial-01/validation_report.json
```

Indexing makes the uploaded FTP files available to the server-side validation workflow. You can confirm that `data01.raw` appears in the study's Files tab in the [MetaboLights test editor](https://wwwdev.ebi.ac.uk/metabolights/editor). If you omit `--sync-data-files`, index the files manually in the website before remote validation.

Open `tutorials/tutorial-01/validation_report.json`. A successful result has no validation errors. If the report contains errors, correct the local metadata, repeat the folder check, upload the changed metadata, and run remote validation again.

`mtblspy` also supports local validation, but it requires an additional local validation bundle and OPA setup. That advanced setup is intentionally outside this introductory tutorial; `mtbls submission validate --help` lists the available local-validation options.
