# Recent Changes

_Source repo: `dfitch8899/docs-pipeline-test`_

## Refactor documentation generation and changelog handling

**Author**: dfitch8899 (d.fitch8899@gmail.com)

**Date**: 2026-03-19T10:31:37-04:00

**Commit**: `3956c99b`

### Changes

```diff
    Refactor documentation generation and changelog handling
    
    Updated the documentation generation process to include changelog entries and handle new commit tracking. Enhanced file inclusion criteria and improved error handling.
diff --git a/docs-bot/main.py b/docs-bot/main.py
index 7553db3..fc04de7 100644
--- a/docs-bot/main.py
+++ b/docs-bot/main.py
@@ -16,101 +16,156 @@ BACK_ROOT = Path(".")
 FRONTEND_REPO = "dfitch8899/flash-front-demo"
 BACKEND_REPO = "dfitch8899/docs-pipeline-test"
 
-INCLUDE_EXT = {".tsx", ".ts", ".js", ".jsx", ".md", ".json", ".css", ".py"}
-MAX_FILE_SIZE = 100_000  # bytes
+INCLUDE_EXT = {".tsx", ".ts", ".js", ".jsx", ".md", ".json", ".css", ".py", ".txt"}
+MAX_DIFF_SIZE = 50_000  # bytes
 
-BACK_EXCLUDE_DIRS = {".git", "docs", "flash-front", ".github", "__pycache__", "node_modules", ".venv"}
+BACK_EXCLUDE_DIRS = {".git", "docs", "flash-front", ".github", "__pycache__", "node_modules", ".venv", ".env"}
 
-DOC_STYLE_INSTRUCTIONS = """Structure the documentation as follows, even when there is little code:
+CHANGELOG_STYLE_INSTRUCTIONS = """Analyze the git diff and create a concise changelog entry summarizing what changed.
 
-1. **Title**: Clear feature/system name and subtitle (e.g. "X Documentation: Architecture, Flow, and Security Measures").
+Format the output as follows:
 
-2. **Overview**: 1–2 short paragraphs describing what the feature does and main components (e.g. where files are stored, what services are involved).
+**Summary**: 1-2 sentences describing the overall change.
 
-3. **Architecture**: A "Key Files" section with a table: columns File (path) and Purpose. Optionally a simple ASCII diagram (e.g. Frontend → API → Storage) if it helps.
+**Files Changed**: List each modified file with a brief description of what changed in it (added, modified, removed).
 
-4. **Flow**: Numbered steps (Upload Flow, Download Flow, etc.). For each step: brief description, then a small code snippet only where it adds clarity. Use "1. User / Client ...", "2. Server ..." style.
+**Key Changes**: Bullet points of the most important additions/modifications:
+- For new features: what capability was added
+- For fixes: what bug/issue was fixed
+- For refactoring: what was improved or simplified
+- Include specific line counts if substantial (e.g., "Added 50 lines of validation logic")
 
-5. **Configuration**: Environment variables in a table: Variable, Description, Default. List only what the code actually uses or mentions.
+**Breaking Changes** (if any): List any changes that might break existing code or APIs.
 
-6. **Database Schema** (if applicable): Model/table definition as a single code block with brief explanation.
+**Testing Notes** (if evident from code): Any test files added or modified that indicate what should be tested.
 
-7. **Security Measures**: Subsections (Authentication, Validation, Error handling, etc.) with short bullet points. No long prose.
-
-8. **Error Handling**: Table of Status code and Description for API errors if relevant.
-
-9. **UI Components** (if applicable): Bullet list of components and what they do (e.g. "AttachmentPreview: shows thumbnails, progress, remove button").
-
-Keep the tone technical and concise. Prefer tables and bullets over paragraphs. Include code only when it illustrates the flow or contract; otherwise reference file paths and purpose."""
+Keep the tone technical and brief. Focus on what changed and why it matters to the codebase."""
 
 
 # -------------------------------------------------------
-# Helper: get changed or all files from a git repo
+# Helper: get only new commits since last documented run
 # -------------------------------------------------------
-def get_files(repo_path: Path, all_files: bool = False) -> list:
-    if not all_files:
-        log = subprocess.check_output(
-            ["git", "-C", str(repo_path), "log", "--format=%H %ae", "-20"],
+def get_new_commits(repo_path: Path) -> list:
+    try:
+        log_output = subprocess.check_output(
+            ["git", "-C", str(repo_path), "log", "--format=%H %ae", "-50"],
         ).decode().splitlines()
         human_commits = [
-            line.split()[0] for line in log
-            if "docs-bot" not in line
+            line.split()[0] for line in log_output
+            if line and "docs-bot" not in line
         ]
-        if len(human_commits) >= 2:
-            files = subprocess.check_output(
-                ["git", "-C", str(repo_path), "diff", "--name-only",
-                 f"{human_commits[1]}..{human_commits[0]}"],
-            ).decode().splitlines()
-            if files:
-                return files
-        elif len(human_commits) == 1:
-            files = subprocess.check_output(
-                ["git", "-C", str(repo_path), "diff-tree", "--no-commit-id",
-                 "-r", "--name-only", human_commits[0]],
-            ).decode().splitlines()
-            if files:
-                return files
-    # fallback: return all tracked files
-    return subprocess.check_output(
-        ["git", "-C", str(repo_path), "ls-files"],
-    ).decode().splitlines()
+        if not human_commits:
+            return []
+
+        # Use a per-repo tracking file
+        last_file = DOCS_DIR / f".last_{repo_path.name}_commit"
+        if last_file.exists():
+            last_hash = last_file.read_text().strip()
+            if last_hash in human_commits:
+                idx = human_commits.index(last_hash)
+                new_commits = human_commits[:idx]
+                if not new_commits:
+                    print(f"No new commits since last run ({last_hash[:8]})")
+                    return []
+                last_file.write_text(new_commits[0])
+                return new_commits
+
+        # First run — document only the latest commit
+        last_file.write_text(human_commits[0])
+        return [human_commits[0]]
+
+    except subprocess.CalledProcessError as e:
+        print(f"Error getting commits for {repo_path}: {e}")
+        return []
 
 
 # -------------------------------------------------------
-# Helper: build markdown from a list of files
+# Helper: get diff and commit info for a single commit
 # -------------------------------------------------------
-def build_raw_md(files: list, root: Path, repo_name: str) -> str:
-    lines = [f"# Components\n\n", f"_Source repo: `{repo_name}`_\n\n"]
-    for f in files:
-        path = root / f
-        if not path.exists() or path.is_dir():
-            continue
-        if path.suffix.lower() not in INCLUDE_EXT and path.name not in ("README.md",):
-            continue
-        try:
-            size = path.stat().st_size
-            if size > MAX_FILE_SIZE:
-                lines.append(f"## `{f}`\n\n*(file too large to include)*\n\n")
-                continue
-            content = path.read_text(encoding="utf-8", errors="replace")
-        except Exception as e:
-            lines.append(f"## `{f}`\n\n*(read error: {e})*\n\n")
+def get_commit_changes(repo_path: Path, commit_hash: str) -> dict:
+    try:
+        info_output = subprocess.check_output(
+            ["git", "-C", str(repo_path), "show", "-s", "--format=%an|%ae|%aI|%B", commit_hash],
+        ).decode().strip()
+        parts = info_output.split("|", 3)
+        author = parts[0]
+        email = parts[1]
+        timestamp = parts[2]
+        message = parts[3] if len(parts) > 3 else ""
+
+        diff_output = subprocess.check_output(
+            ["git", "-C", str(repo_path), "show", commit_hash],
+        ).decode()
+
+        # Filter diff to only relevant lines
+        diff_lines = []
+        for line in diff_output.split("\n"):
+            if (
+                line.startswith("diff --git")
+                or line.startswith("index ")
+                or line.startswith("---")
+                or line.startswith("+++")
+                or line.startswith("@@")
+                or line.startswith("+")
+                or line.startswith("-")
+                or line.startswith(" ")
+            ):
+                diff_lines.append(line)
+
+        diff = "\n".join(diff_lines[:2000])  # cap lines
+
+        return {
+            "hash": commit_hash,
+            "author": author,
+            "email": email,
+            "timestamp": timestamp,
+            "message": message.strip(),
+            "diff": diff,
+        }
+    except subprocess.CalledProcessError as e:
+        print(f"Error getting commit info for {commit_hash}: {e}")
+        return None
+
+
+# -------------------------------------------------------
+# Helper: build raw changelog markdown from commits
+# -------------------------------------------------------
+def build_changelog_md(commits: list, repo_name: str) -> str:
+    if not commits:
+        return f"# Changelog\n\n_Source repo: `{repo_name}`_\n\nNo new commits to document.\n"
+
+    lines = ["# Recent Changes\n\n", f"_Source repo: `{repo_name}`_\n\n"]
+
+    for commit in commits:
+        if not commit:
             continue
-        ext = path.suffix.lower()
-        lang = {".tsx": "tsx", ".ts": "ts", ".js": "js", ".jsx": "js", ".md": "md", ".json": "json", ".css": "css", ".py": "python"}.get(ext, "")
-        lines.append(f"## `{f}`\n\n```{lang}\n{content.strip()}\n```\n\n")
+        lines.append(f"## {commit['message'].split(chr(10))[0]}\n\n")
+        lines.append(f"**Author**: {commit['author']} ({commit['email']})\n\n")
+        lines.append(f"**Date**: {commit['timestamp']}\n\n")
+        lines.append(f"**Commit**: `{commit['hash'][:8]}`\n\n")
+
+        if commit["diff"]:
+            lines.append("### Changes\n\n")
+            lines.append("```diff\n")
+            lines.append(commit["diff"][:MAX_DIFF_SIZE])
+            if len(commit["diff"]) > MAX_DIFF_SIZE:
+                lines.append("\n... (diff truncated) ...")
+            lines.append("\n```\n\n")
+        else:
+            lines.append("*(No tracked file changes)*\n\n")
+
     return "".join(lines)
 
 
 # -------------------------------------------------------
-# Helper: reformat with Claude
+# Helper: summarize with Claude
 # -------------------------------------------------------
-def format_doc_with_ai(raw_markdown: str) -> str:
+def summarize_changes_with_ai(raw_changelog: str) -> str:
     if os.environ.get("USE_AI_SUMMARY", "").lower() not in ("true", "1", "yes"):
-        return raw_markdown
+        return raw_changelog
     api_key = os.environ.get("ANTHROPIC_API_KEY")
     if not api_key:
-        return raw_markdown
+        return raw_changelog
     try:
         from anthropic import Anthropic
         client = Anthropic(api_key=api_key)
@@ -121,20 +176,20 @@ def format_doc_with_ai(raw_markdown: str) -> str:
                 r = client.messages.create(
                     model=m,
                     max_tokens=8192,
-                    system=DOC_STYLE_INSTRUCTIONS,
+                    system=CHANGELOG_STYLE_INSTRUCTIONS,
                     messages=[
-                        {"role": "user", "content": "Turn this raw code dump into structured documentation following the instructions above. Output only the new markdown, no preamble.\n\n" + raw_markdown},
+                        {"role": "user", "content": "Analyze these git changes and create a structured changelog. Output only the new markdown, no preamble.\n\n" + raw_changelog},
                     ],
                 )
                 out = (r.content[0].text if r.content else "").strip()
-                return out if out else raw_markdown
+                return out if out else raw_changelog
             except Exception as e:
                 if ("404" in str(e) or "not_found" in str(e).lower()) and m != fallback:
                     continue
                 raise
     except Exception as e:
-        print("AI format failed:", e)
-        return raw_markdown
+        print("AI summary failed:", e)
+        return raw_changelog
 
 
 # -------------------------------------------------------
@@ -177,40 +232,38 @@ def publish_to_confluence(md_path: Path, title: str) -> None:
 
 
 # -------------------------------------------------------
-# Frontend docs
+# Frontend changelog
 # -------------------------------------------------------
-print("=== FRONTEND ===")
-front_files = get_files(FRONT_ROOT)
-print("Frontend files:", front_files)
-front_raw = build_raw_md(front_files, FRONT_ROOT, FRONTEND_REPO)
-front_final = format_doc_with_ai(front_raw)
-front_doc = DOCS_DIR / "frontend-components.md"
-front_doc.write_text(front_final)
-print("Generated:", front_doc)
-publish_to_confluence(front_doc, "Frontend Components")
+print("=== FRONTEND CHANGELOG ===")
+front_commits = get_new_commits(FRONT_ROOT)
+print(f"Found {len(front_commits)} new frontend commits")
+if front_commits:
+    front_commit_details = [get_commit_changes(FRONT_ROOT, c) for c in front_commits]
+    front_commit_details = [c for c in front_commit_details if c]
+    front_raw = build_changelog_md(front_commit_details, FRONTEND_REPO)
+    front_final = summarize_changes_with_ai(front_raw)
+    front_doc = DOCS_DIR / "frontend-changelog.md"
+    front_doc.write_text(front_final)
+    print("Generated:", front_doc)
+    publish_to_confluence(front_doc, "Frontend Changelog")
+else:
+    print("No new frontend commits, skipping.")
 
 
 # -------------------------------------------------------
-# Backend docs
+# Backend changelog
 # -------------------------------------------------------
-print("=== BACKEND ===")
-back_files_raw = get_files(BACK_ROOT, all_files=False)
-back_files = [
-    f for f in back_files_raw
-    if not any(f.startswith(ex) for ex in BACK_EXCLUDE_DIRS)
-]
-
-# if filtering removed everything, fall back to all tracked files
-if not back_files:
-    back_files = [
-        f for f in get_files(BACK_ROOT, all_files=True)
-        if not any(f.startswith(ex) for ex in BACK_EXCLUDE_DIRS)
-    ]
-
-print("Backend files:", back_files)
-back_raw = build_raw_md(back_files, BACK_ROOT, BACKEND_REPO)
-back_final = format_doc_with_ai(back_raw)
-back_doc = DOCS_DIR / "backend-components.md"
-back_doc.write_text(back_final)
-print("Generated:", back_doc)
-publish_to_confluence(back_doc, "Backend Components")
+print("=== BACKEND CHANGELOG ===")
+back_commits = get_new_commits(BACK_ROOT)
+print(f"Found {len(back_commits)} new backend commits")
+if back_commits:
+    back_commit_details = [get_commit_changes(BACK_ROOT, c) for c in back_commits]
+    back_commit_details = [c for c in back_commit_details if c]
+    back_raw = build_changelog_md(back_commit_details, BACKEND_REPO)
+    back_final = summarize_changes_with_ai(back_raw)
+    back_doc = DOCS_DIR / "backend-changelog.md"
+    back_doc.write_text(back_final)
+    print("Generated:", back_doc)
+    publish_to_confluence(back_doc, "Backend Changelog")
+else:
+    print("No new backend commits, skipping.")
```

