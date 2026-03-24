**Summary**: Introduces Claude-powered intelligent document routing to the docs pipeline, adding a pre-publish analysis step that determines whether each generated changelog should be created as a new page, appended to, or used to rewrite an existing Confluence page.

**Files Changed**:
- `docs-bot/main.py` — Added two new helper functions, refactored `publish_to_confluence`, and restructured the main workflow into discrete numbered steps (~172 lines added).

**Key Changes**:
- **Added `get_confluence_structure()`**: Fetches the parent Confluence page and all child pages (titles + content previews) before any publishing occurs, providing context for intelligent routing decisions.
- **Added `analyze_docs_with_claude()`**: Sends the existing Confluence page structure and newly generated docs to Claude (with `claude-sonnet-4-6` primary, `claude-3-haiku-20240307` fallback) and returns a JSON decision map specifying `CREATE`, `ADD`, or `REWRITE` per document. Falls back to `REWRITE` for all docs if analysis fails or no API key is present.
- **Refactored `publish_to_confluence()`**: Added `action` parameter (`"CREATE"` | `"ADD"` | `"REWRITE"`) and implemented distinct handling for each case:
  - `ADD` + existing page: appends new HTML to existing content
  - `REWRITE` + existing page: replaces content (prior behavior)
  - `ADD`/`REWRITE` + no existing page: falls back to creating the page
  - `CREATE` + existing page: skips to prevent duplicates
- **Restructured main workflow** into four explicit steps: (1) fetch Confluence structure, (2) generate changelogs, (3) analyze with Claude, (4) publish with determined actions — replacing direct `publish_to_confluence` calls after each changelog generation.

**Breaking Changes**:
- `publish_to_confluence` signature changed: new `action` parameter added (defaults to `"REWRITE"`, preserving existing behavior for direct callers).
- Publishing no longer happens immediately after each changelog is generated; all publishing is deferred to Step 4.

**Testing Notes**: No test files modified. Manual verification should cover all six action/existence combinations in `publish_to_confluence`, Claude API fallback behavior, JSON parsing with and without markdown wrapping in the Claude response, and the `get_confluence_structure` error path when env vars are missing.