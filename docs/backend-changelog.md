**Summary**: Removes the `scripts/` directory and its sole file, `publish_docs.py`, a utility script for previewing Confluence documentation payloads.

**Files Changed**:
- `scripts/publish_docs.py` — Deleted entirely (19 lines removed)

**Key Changes**:
- Removed CLI script that accepted a `--files` argument, read file contents, and printed a formatted Confluence payload preview (page title, parent page ID, and body) to stdout
- Eliminated dependency on `CONFLUENCE_PARENT_PAGE_ID` environment variable consumed by this script

**Breaking Changes**:
- Any pipeline steps, CI jobs, or workflows invoking `scripts/publish_docs.py` will now fail; callers must be updated or removed accordingly

**Testing Notes**: No test files were added or modified; no replacement implementation is evident from this diff.