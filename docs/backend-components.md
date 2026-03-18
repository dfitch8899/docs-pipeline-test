# Docs Pipeline Documentation: Architecture, Flow, and Security Measures

## Overview

The docs pipeline automates the publishing of Markdown documentation files to Confluence. It reads one or more local files, transforms their filenames into page titles, and constructs a payload preview destined for the Confluence API.

The pipeline is minimal by design: a single Python script consumes file paths and environment configuration, then outputs a structured preview of what would be published. A sample `test.md` fixture is included for validation.

---

## Architecture

### Key Files

| File | Purpose |
|---|---|
| `scripts/publish_docs.py` | Entry-point script; reads files, builds Confluence payload preview, and prints output |
| `test.md` | Sample Markdown fixture used to test the pipeline |

### Flow Diagram

```
CLI (--files) → publish_docs.py → Reads file content → Formats payload → stdout preview
                       ↑
              CONFLUENCE_PARENT_PAGE_ID (env)
```

---

## Flow

### Publish Flow

1. **Caller invokes the script** with a space-separated list of file paths via the `--files` argument:
   ```bash
   python scripts/publish_docs.py --files "test.md other-doc.md"
   ```

2. **Script splits the file list** and iterates over each path:
   ```python
   files = args.files.split()
   for f in files:
       content = Path(f).read_text()
   ```

3. **Page title is derived** from the filename stem by replacing hyphens with spaces and applying title-case:
   ```python
   Path(f).stem.replace('-', ' ').title()
   # "my-new-doc.md" → "My New Doc"
   ```

4. **Parent page ID is resolved** from the environment variable `CONFLUENCE_PARENT_PAGE_ID`.

5. **Payload preview is printed to stdout**, showing title, parent page ID, and full page body per file:
   ```
   === CONFLUENCE PAYLOAD PREVIEW ===

   Page title: Test
   Parent page ID: 12345
   Body:
   test.md

   ---
   ```

---

## Configuration

| Variable | Description | Default |
|---|---|---|
| `CONFLUENCE_PARENT_PAGE_ID` | Confluence page ID under which new pages will be created | None (must be set) |

---

## Security Measures

### Authentication
- No authentication is implemented in the current script; credentials are expected to be injected at a higher layer (e.g., CI environment secrets) before the real API call is made.

### Validation
- The `--files` argument is required; `argparse` will exit with an error if omitted.
- No explicit check is performed for missing or unreadable files — `Path.read_text()` will raise a `FileNotFoundError` or `PermissionError` at runtime.

### Error Handling
- File read errors surface as unhandled exceptions and will cause a non-zero exit code, which is compatible with CI pipeline failure detection.
- `CONFLUENCE_PARENT_PAGE_ID` being unset results in `None` being printed in the preview but does not halt execution.

---

## Error Handling

| Condition | Behaviour |
|---|---|
| `--files` argument missing | `argparse` exits with code `2` and prints usage |
| File path does not exist | `FileNotFoundError` raised; script exits with code `1` |
| `CONFLUENCE_PARENT_PAGE_ID` not set | `None` printed as parent page ID; execution continues |