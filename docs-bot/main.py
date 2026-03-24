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
# Helper: get Confluence page structure
# -------------------------------------------------------
def get_confluence_structure() -> dict:
    """Fetch parent page and all child pages with titles, hierarchy, and content."""
    base = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    email = os.environ.get("CONFLUENCE_USER_EMAIL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")
    parent_id = os.environ.get("CONFLUENCE_PARENT_PAGE_ID")
    
    if not all((base, email, api_token, parent_id)):
        print("Confluence structure: skipped (missing CONFLUENCE_* env vars)")
        return {}
    
    try:
        api_base = f"{base}/wiki/rest/api"
        auth = (email, api_token)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        
        # Get parent page info
        r = requests.get(f"{api_base}/content/{parent_id}", params={"expand": "space,body.storage"}, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        parent_data = r.json()
        parent_content = parent_data.get("body", {}).get("storage", {}).get("value", "")
        
        structure = {
            "parent": {
                "id": parent_id,
                "title": parent_data.get("title", "Unknown"),
                "content": parent_content,
            },
            "children": []
        }
        
        # Get all child pages with content
        r = requests.get(f"{api_base}/content/{parent_id}/child/page", params={"expand": "body.storage", "limit": 100}, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        
        for page in r.json().get("results", []):
            child_content = page.get("body", {}).get("storage", {}).get("value", "")
            structure["children"].append({
                "id": page.get("id"),
                "title": page.get("title", "Unknown"),
                "content": child_content,
            })
        
        print(f"Confluence structure: fetched parent + {len(structure['children'])} child pages")
        return structure
        
    except Exception as e:
        print(f"Error fetching Confluence structure: {e}")
        return {}


# -------------------------------------------------------
# Helper: analyze docs with Claude to determine ADD/CREATE/REWRITE
# -------------------------------------------------------
def analyze_docs_with_claude(confluence_structure: dict, new_docs: dict) -> dict:
    """
    Send Confluence structure + new docs to Claude and get ADD/CREATE/REWRITE decisions.
    
    Args:
        confluence_structure: dict with 'parent' and 'children' keys from get_confluence_structure()
        new_docs: dict mapping doc title -> markdown content
    
    Returns:
        dict mapping doc title -> {"action": "CREATE|ADD|REWRITE", "reason": "..."}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Claude analysis skipped (no ANTHROPIC_API_KEY)")
        return {title: {"action": "REWRITE", "reason": "Default (no API key)"} for title in new_docs.keys()}
    
    try:
        from anthropic import Anthropic
        
        # Format confluence structure for Claude
        existing_pages = []
        for child in confluence_structure.get("children", []):
            existing_pages.append(f"- Title: {child['title']}\n  Content preview: {child['content'][:500]}...")
        
        confluence_str = "\n".join(existing_pages) if existing_pages else "No existing child pages"
        
        # Format new docs
        new_docs_str = "\n\n".join([
            f"### {title}\n{content[:500]}..."
            for title, content in new_docs.items()
        ])
        
        prompt = f"""You are analyzing documentation updates. Based on the existing Confluence structure and new documentation being generated, determine whether each new doc should:
- CREATE: New page (doesn't exist yet)
- ADD: Append to existing page (enhance without replacing)
- REWRITE: Replace existing page content (already exists and needs full update)

## Existing Confluence Pages:
{confluence_str}

## New Documentation to Publish:
{new_docs_str}

## Decision Format:
Return ONLY valid JSON (no markdown, no preamble):
{{
  "doc_title_1": {{"action": "CREATE", "reason": "Brief reason"}},
  "doc_title_2": {{"action": "REWRITE", "reason": "Brief reason"}}
}}

Decide now:"""
        
        client = Anthropic(api_key=api_key)
        model = os.environ.get("CLAUDE_DOC_MODEL", "claude-sonnet-4-6")
        fallback = "claude-3-haiku-20240307"
        
        for m in (model, fallback):
            try:
                r = client.messages.create(
                    model=m,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = (r.content[0].text if r.content else "").strip()
                
                # Extract JSON from response
                import json
                try:
                    # Try direct parse first
                    decisions = json.loads(response_text)
                except json.JSONDecodeError:
                    # Try to extract JSON from response if it has other text
                    import re
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        decisions = json.loads(json_match.group())
                    else:
                        raise
                
                print("Claude analysis results:")
                for title, decision in decisions.items():
                    print(f"  {title}: {decision['action']} ({decision.get('reason', '')})")
                
                return decisions
                
            except Exception as e:
                if ("404" in str(e) or "not_found" in str(e).lower()) and m != fallback:
                    continue
                print(f"Claude analysis error with {m}: {e}")
                raise
        
    except Exception as e:
        print(f"Claude analysis failed: {e}")
        # Default to REWRITE for all
        return {title: {"action": "REWRITE", "reason": "Default (analysis failed)"} for title in new_docs.keys()}


# -------------------------------------------------------
# Helper: publish a doc to Confluence
# -------------------------------------------------------
def publish_to_confluence(md_path: Path, title: str, action: str = "REWRITE") -> None:
    """
    Publish markdown to Confluence with support for ADD/CREATE/REWRITE actions.
    
    Args:
        md_path: Path to markdown file
        title: Page title
        action: "CREATE" (new page), "ADD" (append to existing), "REWRITE" (replace existing or create)
    """
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
    
    # Get space key
    r = requests.get(f"{api_base}/content/{parent_id}", params={"expand": "space"}, auth=auth, headers=headers, timeout=30)
    r.raise_for_status()
    space_key = r.json()["space"]["key"]
    
    # Convert markdown to HTML
    md_text = md_path.read_text(encoding="utf-8")
    html = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    new_html = html if html.strip().startswith("<") else f"<p>{html}</p>"
    
    # Check if page already exists
    r = requests.get(f"{api_base}/content/{parent_id}/child/page", auth=auth, headers=headers, timeout=30)
    r.raise_for_status()
    existing = next((p for p in r.json().get("results", []) if p.get("title") == title), None)
    
    if action == "ADD" and existing:
        # ADD: Append to existing page
        page_id = existing["id"]
        r = requests.get(f"{api_base}/content/{page_id}", params={"expand": "body.storage,version"}, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        page_data = r.json()
        existing_html = page_data.get("body", {}).get("storage", {}).get("value", "")
        version = page_data["version"]["number"] + 1
        
        # Combine existing + new content
        combined_html = f"{existing_html}\n\n{new_html}"
        body_payload = {"storage": {"value": combined_html, "representation": "storage"}}
        
        r = requests.put(
            f"{api_base}/content/{page_id}",
            json={"id": page_id, "type": "page", "title": title, "version": {"number": version}, "body": body_payload},
            auth=auth, headers=headers, timeout=30
        )
        r.raise_for_status()
        print(f"Confluence: '{title}' APPENDED at {r.json().get('_links', {}).get('webui', '')}")
        
    elif action == "REWRITE" and existing:
        # REWRITE: Replace existing page
        page_id = existing["id"]
        r = requests.get(f"{api_base}/content/{page_id}", params={"expand": "body.storage,version"}, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        version = r.json()["version"]["number"] + 1
        
        body_payload = {"storage": {"value": new_html, "representation": "storage"}}
        r = requests.put(
            f"{api_base}/content/{page_id}",
            json={"id": page_id, "type": "page", "title": title, "version": {"number": version}, "body": body_payload},
            auth=auth, headers=headers, timeout=30
        )
        r.raise_for_status()
        print(f"Confluence: '{title}' REWRITTEN at {r.json().get('_links', {}).get('webui', '')}")
        
    elif action == "ADD" and not existing:
        # ADD requested but page doesn't exist → CREATE it instead
        body_payload = {"storage": {"value": new_html, "representation": "storage"}}
        payload = {"type": "page", "title": title, "ancestors": [{"id": parent_id}], "space": {"key": space_key}, "body": body_payload}
        r = requests.post(f"{api_base}/content", json=payload, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        print(f"Confluence: '{title}' CREATED (ADD requested but didn't exist) at {r.json().get('_links', {}).get('webui', '')}")
        
    elif action == "REWRITE" and not existing:
        # REWRITE requested but page doesn't exist → CREATE it instead
        body_payload = {"storage": {"value": new_html, "representation": "storage"}}
        payload = {"type": "page", "title": title, "ancestors": [{"id": parent_id}], "space": {"key": space_key}, "body": body_payload}
        r = requests.post(f"{api_base}/content", json=payload, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        print(f"Confluence: '{title}' CREATED (REWRITE requested but didn't exist) at {r.json().get('_links', {}).get('webui', '')}")
        
    else:
        # CREATE: Fresh new page
        if existing:
            print(f"Confluence: '{title}' already exists (action=CREATE), skipping to avoid duplicate")
            return
        body_payload = {"storage": {"value": new_html, "representation": "storage"}}
        payload = {"type": "page", "title": title, "ancestors": [{"id": parent_id}], "space": {"key": space_key}, "body": body_payload}
        r = requests.post(f"{api_base}/content", json=payload, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        print(f"Confluence: '{title}' CREATED at {r.json().get('_links', {}).get('webui', '')}")


# -------------------------------------------------------
# MAIN WORKFLOW
# -------------------------------------------------------

print("=== STEP 1: FETCH CONFLUENCE STRUCTURE ===")
confluence_structure = get_confluence_structure()

print("\n=== STEP 2: GENERATE CHANGELOGS ===")
generated_docs = {}

# Frontend changelog
print("\n--- FRONTEND CHANGELOG ---")
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
    generated_docs["Frontend Changelog"] = front_final
else:
    print("No new frontend commits, skipping.")

# Backend changelog
print("\n--- BACKEND CHANGELOG ---")
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
    generated_docs["Backend Changelog"] = back_final
else:
    print("No new backend commits, skipping.")

# -------------------------------------------------------
# STEP 3: ANALYZE WITH CLAUDE FOR ADD/CREATE/REWRITE
# -------------------------------------------------------
print("\n=== STEP 3: ANALYZE DOCS WITH CLAUDE ===")
if generated_docs:
    decisions = analyze_docs_with_claude(confluence_structure, generated_docs)
else:
    print("No docs generated, skipping analysis.")
    decisions = {}

# -------------------------------------------------------
# STEP 4: PUBLISH TO CONFLUENCE WITH DETERMINED ACTIONS
# -------------------------------------------------------
print("\n=== STEP 4: PUBLISH TO CONFLUENCE ===")
for doc_title, decision in decisions.items():
    action = decision.get("action", "REWRITE")
    reason = decision.get("reason", "")
    
    # Map doc titles to file paths
    doc_map = {
        "Frontend Changelog": DOCS_DIR / "frontend-changelog.md",
        "Backend Changelog": DOCS_DIR / "backend-changelog.md",
    }
    
    doc_path = doc_map.get(doc_title)
    if doc_path and doc_path.exists():
        print(f"\nPublishing '{doc_title}' ({action}: {reason})")
        publish_to_confluence(doc_path, doc_title, action=action)
    else:
        print(f"\nSkipping '{doc_title}' (file not found)")

print("\n=== WORKFLOW COMPLETE ===")
