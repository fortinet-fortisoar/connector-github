#### Following enhancements have been made to the GitHub connector in version 2.2.0:
### Fixed Binary File Corruption in Repository Actions

Fixed an issue where binary files such as `.zip`, `.tgz`, and `.tar.gz` could become corrupted while using the Update Remote Repository and Push Changes actions.

- **Update Remote Repository**: Improved file handling to safely copy and replace binary files without modifying their contents.
- **Push Changes**: Updated binary file handling to correctly create Git blobs using Base64 encoding, ensuring that binary files are pushed to the remote repository without corruption.

This ensures that binary files retain their original content and remain valid after repository synchronization and push operations.

