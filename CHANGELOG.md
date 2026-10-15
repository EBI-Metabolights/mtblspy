## v0.1.1 (2026-10-15)

### Fix

- **missing-cicd-components**: cicd components updated and versioning is integrated with cicd

## v0.1.0 (2026-10-15)

### Feat

- Refactor submission command handling to utilize shared client context and improve JWT token management
- Enhance JWT token support across submission commands and update related tests
- Enhance submission client with JWT token support and update related commands
- Add initial GitLab CI configuration for submission pipeline
- Add support for JWT token authentication in login command and enhance submission client functionality
- Add example submission folders and enhance validation error handling in tests
- Update documentation to reflect changes in study ID usage and metadata validation processes
- Enhance folder check command to support output report and validate metadata filenames against study ID
- Add command to clean FTP temporary files and integrate progress reporting for data uploads
- Add commands to download ISA-Tab and result file templates with validation endpoint options
- Enhance validation command with local and remote options, including WASM support
- Implement upload-data command to facilitate data file uploads to the private FTP area
- Rename upload-metadata command to metadata-upload and enhance file selection options
- Implement compress-data-files command to zip .d directories and update metadata references
- Enhance validation-debug command with local validation comparison and detailed reporting
- Enhance local validation input parsing with additional metadata and structure validation
- Implement local validation command and configuration management
- enhance submission commands with JSON output options and add study creation template
- add validation-debug command to analyze ISA JSON and study validation root causes, and set default input path for submission creation.

### Refactor

- update default base URL, standardize credential base URL handling in tests, and improve authentication error messaging and credential store logging.
- remove submission pipeline CI script and configuration
- Remove recommended pipeline pattern section from submission workflow guide
