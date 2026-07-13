# Submission Example Folders

These folders provide small ISA-Tab and data-file examples for trying the submission commands without preparing a full study.

Use the valid example with:

```bash
mtbls submission check-folders MTBLSXXX \
  --metadata-files-path examples/submission/valid/MTBLSXXX \
  --data-files-path examples/submission/valid/MTBLSXXX/FILES \
  -o folder_check_report.json
```

The `invalid-*` folders are intentionally broken so users and automated tests can exercise error handling.

| Folder | Purpose |
| --- | --- |
| `valid/MTBLSXXX` | Complete minimal metadata and matching data files. |
| `invalid-bad-names/MTBLSXXX` | Invalid metadata/data filenames and bad data references. |
| `invalid-incomplete-metadata/MTBLSXXX` | Missing required metadata content and incomplete sample/assay consistency. |

These files are examples only. Replace `MTBLSXXX` with the accession assigned to your provisional study before uploading real metadata.

To adapt the valid example for your own provisional study:

1. Copy `valid/MTBLSXXX` to a working folder.
2. Rename the copied folder from `MTBLSXXX` to your study ID, for example `MTBLSxxx` or `REQxxx`.
3. Rename study-specific metadata files to use the same ID: `s_<study_id>.txt`, `a_<study_id>_lc-ms.txt`, and `m_<study_id>.tsv`.
4. Update the study ID inside `i_Investigation.txt`, including the assay filename listed in the `STUDY ASSAYS` section.
5. Update the metabolite assignment filename references inside the assay file.
6. Run `mtbls submission check-folders` before upload.
