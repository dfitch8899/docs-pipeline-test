import os
import subprocess
from pathlib import Path

import markdown
import requests
from dotenv import load_dotenv

load_dotenv()

DOCS_DIR = Path("docs")
DOCS_DIR.mkdir(exist_ok=True)

FRONT_ROOT = Path("flash-front")
BACK_ROOT = Path(".")
FRONTEND_REPO = "dfitch8899/flash-front-demo"
BACKEND_REPO = "dfitch8899/docs-pipeline-test"

INCLUDE_EXT = {".tsx", ".ts", ".js", ".jsx", ".md", ".json", ".css", ".py", ".txt"}
MAX_DIFF_SIZE = 50_000  # bytes

BACK_EXCLUDE_DIRS = {".git", "docs", "flash-front", ".github", "__pycache__", "node_modules", ".venv", ".env"}

CHANGELOG_STYLE_INSTRUCTIONS = """Analyze the git diff and create a concise changelog entry summarizing what changed.

Format the output as follows:

**Summary**: 1-2 sentences describing the overall change.

**Files Changed**: List each modified file with a brief description of what changed in it (added, modified, removed).

**Key Changes**: Bullet points of the most important additions/modifications:
- For new features: what capability was added
- For fixes: what bug/issue was fixed
- For refactoring: what was improved or simplified
- Include specific line counts if substantial (e.g., "Added 50 lines of validation logic")

**Breaking Changes** (if any): List any changes that might break existing code or APIs.

**Testing Notes** (if evident from code): Any test files added or modified that indicate what should be tested.

Keep the tone technical and brief. Focus on what changed and why it matters to the codebase."""


# -------------------------------------------------------
# Helper: get only new commits since last documented run
# -------------------------------------------------------
def get_new_commits(repo_path: Path) -> list:
    try:
        log_output = subprocess.check_output(
            ["git", "-C", str(repo_path), "log", "--format=%H %ae", "-50"],
        ).decode().splitlines()
        human_commits = [
            line.split()[0] for line in log_output
            if line and "docs-bot" not in line
        ]
        if not human_commits:
            return []

        # Use a per-repo tracking file
        last_file = DOCS_DIR / f".last_{repo_path.name}_commit"
        if last_file.exists():
            last_hash = last_file.read_text().strip()
            if last_hash in human_commits:
                idx = human_commits.index(last_hash)
                new_commits = human_commits[:idx]
                if not new_commits:
                    print(f"No new commits since last run ({last_hash[:8]})")
                    return []
                last_file.write_text(new_commits[0])
                return new_commits

        # First run — document only the latest commit
        last_file.write_text(human_commits[0])
        return [human_commits[0]]

    except subprocess.CalledProcessError as e:
        print(f"Error getting commits for {repo_path}: {e}")
        return []


# -------------------------------------------------------
# Helper: get diff and commit info for a single commit
# -------------------------------------------------------
def get_commit_changes(repo_path: Path, commit_hash: str) -> dict:
    try:
        info_output = subprocess.check_output(
            ["git", "-C", str(repo_path), "show", "-s", "--format=%an|%ae|%aI|%B", commit_hash],
        ).decode().strip()
        parts = info_output.split("|", 3)
        author = parts[0]
        email = parts[1]
        timestamp = parts[2]
        message = parts[3] if len(parts) > 3 else ""

        diff_output = subprocess.check_output(
            ["git", "-C", str(repo_path), "show", commit_hash],
        ).decode()

        # Filter diff to only relevant lines
        diff_lines = []
        for line in diff_output.split("\n"):
            if (
                line.startswith("diff --git")
                or line.startswith("index ")
                or line.startswith("---")
                or line.startswith("+++")
                or line.startswith("@@")
                or line.startswith("+")
                or line.startswith("-")
                or line.startswith(" ")
            ):
                diff_lines.append(line)

        diff = "\n".join(diff_lines[:2000])  # cap lines

        return {
            "hash": commit_hash,
            "author": author,
            "email": email,
            "timestamp": timestamp,
            "message": message.strip(),
            "diff": diff,
        }
    except subprocess.CalledProcessError as e:
        print(f"Error getting commit info for {commit_hash}: {e}")
        return None


# -------------------------------------------------------
# Helper: build raw changelog markdown from commits
# -------------------------------------------------------
def build_changelog_md(commits: list, repo_name: str) -> str:
    if not commits:
        return f"# Changelog\n\n_Source repo: `{repo_name}`_\n\nNo new commits to document.\n"

    lines = ["# Recent Changes\n\n", f"_Source repo: `{repo_name}`_\n\n"]

    for commit in commits:
        if not commit:
            continue
        lines.append(f"## {commit['message'].split(chr(10))[0]}\n\n")
        lines.append(f"**Author**: {commit['author']} ({commit['email']})\n\n")
        lines.append(f"**Date**: {commit['timestamp']}\n\n")
        lines.append(f"**Commit**: `{commit['hash'][:8]}`\n\n")

        if commit["diff"]:
            lines.append("### Changes\n\n")
            lines.append("```diff\n")
            lines.append(commit["diff"][:MAX_DIFF_SIZE])
            if len(commit["diff"]) > MAX_DIFF_SIZE:
                lines.append("\n... (diff truncated) ...")
            lines.append("\n```\n\n")
        else:
            lines.append("*(No tracked file changes)*\n\n")

    return "".join(lines)


# -------------------------------------------------------
# Helper: summarize with Claude
# -------------------------------------------------------
def summarize_changes_with_ai(raw_changelog: str) -> str:
    if os.environ.get("USE_AI_SUMMARY", "").lower() not in ("true", "1", "yes"):
        return raw_changelog
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return raw_changelog
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        model = os.environ.get("CLAUDE_DOC_MODEL", "claude-sonnet-4-6")
        fallback = "claude-3-haiku-20240307"
        for m in (model, fallback):
            try:
                r = client.messages.create(
                    model=m,
                    max_tokens=8192,
                    system=CHANGELOG_STYLE_INSTRUCTIONS,
                    messages=[
                        {"role": "user", "content": "Analyze these git changes and create a structured changelog. Output only the new markdown, no preamble.\n\n" + raw_changelog},
                    ],
                )
                out = (r.content[0].text if r.content else "").strip()
                return out if out else raw_changelog
            except Exception as e:
                if ("404" in str(e) or "not_found" in str(e).lower()) and m != fallback:
                    continue
                raise
    except Exception as e:
        print("AI summary failed:", e)
        return raw_changelog


# -------------------------------------------------------
# Helper: publish a doc to Confluence
# -------------------------------------------------------
def publish_to_confluence(md_path: Path, title: str) -> None:
    base = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    email = os.environ.get("CONFLUENCE_USER_EMAIL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")
    parent_id = os.environ.get("CONFLUENCE_PARENT_PAGE_ID")
    if not all((base, email, api_token, parent_id)):
        print("Confluence: skipped (missing CONFLUENCE_* env vars)")
        return
    api_base = f"{base}/wiki/rest/api"
    auth = (email, api_token)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    r = requests.get(f"{api_base}/content/{parent_id}", params={"expand": "space"}, auth=auth, headers=headers, timeout=30)
    r.raise_for_status()
    space_key = r.json()["space"]["key"]
    md_text = md_path.read_text(encoding="utf-8")
    html = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    storage_value = html if html.strip().startswith("<") else f"<p>{html}</p>"
    body_payload = {"storage": {"value": storage_value, "representation": "storage"}}
    r = requests.get(f"{api_base}/content/{parent_id}/child/page", auth=auth, headers=headers, timeout=30)
    r.raise_for_status()
    existing = next((p for p in r.json().get("results", []) if p.get("title") == title), None)
    if existing:
        page_id = existing["id"]
        r = requests.get(f"{api_base}/content/{page_id}", params={"expand": "body.storage,version"}, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        version = r.json()["version"]["number"] + 1
        r = requests.put(f"{api_base}/content/{page_id}", json={"id": page_id, "type": "page", "title": title, "version": {"number": version}, "body": body_payload}, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        print(f"Confluence: '{title}' updated at", r.json().get("_links", {}).get("webui", ""))
    else:
        payload = {"type": "page", "title": title, "ancestors": [{"id": parent_id}], "space": {"key": space_key}, "body": body_payload}
        r = requests.post(f"{api_base}/content", json=payload, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        print(f"Confluence: '{title}' created at", r.json().get("_links", {}).get("webui", ""))


# -------------------------------------------------------
# Frontend changelog
# -------------------------------------------------------
print("=== FRONTEND CHANGELOG ===")
front_commits = get_new_commits(FRONT_ROOT)
print(f"Found {len(front_commits)} new frontend commits")
if front_commits:
    front_commit_details = [get_commit_changes(FRONT_ROOT, c) for c in front_commits]
    front_commit_details = [c for c in front_commit_details if c]
    front_raw = build_changelog_md(front_commit_details, FRONTEND_REPO)
    front_final = summarize_changes_with_ai(front_raw)
    front_doc = DOCS_DIR / "frontend-changelog.md"
    front_doc.write_text(front_final)
    print("Generated:", front_doc)
    publish_to_confluence(front_doc, "Frontend Changelog")
else:
    print("No new frontend commits, skipping.")


# -------------------------------------------------------
# Backend changelog
# -------------------------------------------------------
print("=== BACKEND CHANGELOG ===")
back_commits = get_new_commits(BACK_ROOT)
print(f"Found {len(back_commits)} new backend commits")
if back_commits:
    back_commit_details = [get_commit_changes(BACK_ROOT, c) for c in back_commits]
    back_commit_details = [c for c in back_commit_details if c]
    back_raw = build_changelog_md(back_commit_details, BACKEND_REPO)
    back_final = summarize_changes_with_ai(back_raw)
    back_doc = DOCS_DIR / "backend-changelog.md"
    back_doc.write_text(back_final)
    print("Generated:", back_doc)
    publish_to_confluence(back_doc, "Backend Changelog")
else:
    print("No new backend commits, skipping.")
