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
FRONTEND_REPO = "dfitch8899/flash-front-demo"

INCLUDE_EXT = {".tsx", ".ts", ".js", ".jsx", ".md", ".json", ".css"}
MAX_FILE_SIZE = 100_000  # bytes

DOC_STYLE_INSTRUCTIONS = """Structure the documentation as follows, even when there is little code:

1. **Title**: Clear feature/system name and subtitle (e.g. "X Documentation: Architecture, Flow, and Security Measures").

2. **Overview**: 1–2 short paragraphs describing what the feature does and main components (e.g. where files are stored, what services are involved).

3. **Architecture**: A "Key Files" section with a table: columns File (path) and Purpose. Optionally a simple ASCII diagram (e.g. Frontend → API → Storage) if it helps.

4. **Flow**: Numbered steps (Upload Flow, Download Flow, etc.). For each step: brief description, then a small code snippet only where it adds clarity. Use "1. User / Client ...", "2. Server ..." style.

5. **Configuration**: Environment variables in a table: Variable, Description, Default. List only what the code actually uses or mentions.

6. **Database Schema** (if applicable): Model/table definition as a single code block with brief explanation.

7. **Security Measures**: Subsections (Authentication, Validation, Error handling, etc.) with short bullet points. No long prose.

8. **Error Handling**: Table of Status code and Description for API errors if relevant.

9. **UI Components** (if applicable): Bullet list of components and what they do (e.g. "AttachmentPreview: shows thumbnails, progress, remove button").

Keep the tone technical and concise. Prefer tables and bullets over paragraphs. Include code only when it illustrates the flow or contract; otherwise reference file paths and purpose."""


# -------------------------------------------------------
# Get changed (or all) files from frontend repo
# -------------------------------------------------------
result = subprocess.run(
    ["git", "-C", str(FRONT_ROOT), "diff", "--name-only", "HEAD~1..HEAD"],
    capture_output=True, text=True
)

if result.returncode != 0:
    # Only one commit — list all tracked files
    files = subprocess.check_output(
        ["git", "-C", str(FRONT_ROOT), "ls-files"],
    ).decode().splitlines()
else:
    files = result.stdout.splitlines()

print("Frontend changes:")
for f in files:
    print("-", f)

# -------------------------------------------------------
# Build raw markdown from file contents
# -------------------------------------------------------
lines = [f"# Frontend Components\n\n", f"_Source repo: `{FRONTEND_REPO}`_\n\n"]

for f in files:
    path = FRONT_ROOT / f
    if not path.exists() or path.is_dir():
        continue
    if path.suffix.lower() not in INCLUDE_EXT and path.name not in ("README.md",):
        continue
    try:
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            lines.append(f"## `{f}`\n\n*(file too large to include)*\n\n")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        lines.append(f"## `{f}`\n\n*(read error: {e})*\n\n")
        continue

    ext = path.suffix.lower()
    lang = {".tsx": "tsx", ".ts": "ts", ".js": "js", ".jsx": "js", ".md": "md", ".json": "json", ".css": "css"}.get(ext, "")
    lines.append(f"## `{f}`\n\n```{lang}\n{content.strip()}\n```\n\n")

raw_md = "".join(lines)


# -------------------------------------------------------
# Optionally reformat with Claude
# -------------------------------------------------------
def format_doc_with_ai(raw_markdown: str) -> str:
    if os.environ.get("USE_AI_SUMMARY", "").lower() not in ("true", "1", "yes"):
        return raw_markdown
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return raw_markdown
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
                    system=DOC_STYLE_INSTRUCTIONS,
                    messages=[
                        {"role": "user", "content": "Turn this raw code dump into structured documentation following the instructions above. Output only the new markdown, no preamble.\n\n" + raw_markdown},
                    ],
                )
                out = (r.content[0].text if r.content else "").strip()
                return out if out else raw_markdown
            except Exception as e:
                if ("404" in str(e) or "not_found" in str(e).lower()) and m != fallback:
                    continue
                raise
    except Exception as e:
        print("AI format failed:", e)
        return raw_markdown


final_md = format_doc_with_ai(raw_md)

# -------------------------------------------------------
# Write final doc
# -------------------------------------------------------
doc_path = DOCS_DIR / "frontend-components.md"
doc_path.write_text(final_md)
print("Generated docs:", doc_path)


# -------------------------------------------------------
# Publish to Confluence (optional)
# -------------------------------------------------------
def publish_to_confluence(md_path: Path) -> None:
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
    title = "Frontend Components"
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
        print("Confluence: page updated at", r.json().get("_links", {}).get("webui", ""))
    else:
        payload = {"type": "page", "title": title, "ancestors": [{"id": parent_id}], "space": {"key": space_key}, "body": body_payload}
        r = requests.post(f"{api_base}/content", json=payload, auth=auth, headers=headers, timeout=30)
        r.raise_for_status()
        print("Confluence: page created at", r.json().get("_links", {}).get("webui", ""))


publish_to_confluence(doc_path)
