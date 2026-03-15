import os
import subprocess
from pathlib import Path

import markdown
import requests
from dotenv import load_dotenv

load_dotenv()

DOCS_DIR = Path("docs")

# Instructions for AI when USE_AI_SUMMARY=true: structure generated docs like formal Confluence docs (Overview, Architecture, Flow, Configuration, Security).
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
DOCS_DIR.mkdir(exist_ok=True)

# Which repo to pull: set FRONTEND_REPO in env to override. To use flash-front-demo: FRONTEND_REPO=dfitch8899/flash-front-demo
FRONTEND_REPO = os.environ.get("FRONTEND_REPO", "NeelMawakar/Flash-Doc-Bot-Testing")
TOKEN = os.environ.get("FRONTEND_REPO_TOKEN")
if not TOKEN:
    raise RuntimeError("FRONTEND_REPO_TOKEN missing")

clone_url = f"https://x-access-token:{TOKEN}@github.com/{FRONTEND_REPO}"
if not Path("flash-front").exists():
    subprocess.run(["git", "clone", clone_url, "flash-front"], check=True)

result = subprocess.run(
    ["git", "-C", "flash-front", "diff", "--name-only", "HEAD~1..HEAD"],
    capture_output=True, text=True
)

if result.returncode != 0:
    # Repo has only one commit, list all files instead
    files = subprocess.check_output(
        ["git", "-C", "flash-front", "ls-files"],
    ).decode().splitlines()
else:
    files = result.stdout.splitlines()

FRONT_ROOT = Path("flash-front")
# Only include files that exist and are text (skip binary / huge files)
INCLUDE_EXT = {".tsx", ".ts", ".jsx", ".js", ".md", ".css", ".json"}
max_size = 500_000  # skip files larger than ~500KB

lines = ["# Frontend Components\n", f"_Source repo: `{FRONTEND_REPO}`_\n"]
for f in files:
    print("-", f)
    path = FRONT_ROOT / f
    if not path.exists() or path.is_dir():
        continue
    if path.suffix.lower() not in INCLUDE_EXT and path.name not in ("README.md",):
        continue
    try:
        size = path.stat().st_size
        if size > max_size:
            lines.append(f"## `{f}`\n\n*(file too large to include)*\n\n")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        lines.append(f"## `{f}`\n\n*(read error: {e})*\n\n")
        continue
    ext = path.suffix.lower()
    lang = "tsx" if ext == ".tsx" else "ts" if ext == ".ts" else "js" if ext in (".js", ".jsx") else "md" if ext == ".md" else "json" if ext == ".json" else "css"
    lines.append(f"## `{f}`\n\n```{lang}\n{content.strip()}\n```\n\n")

raw_md = "".join(lines)


def format_doc_with_ai(raw_markdown: str) -> str:
    """If ANTHROPIC_API_KEY and USE_AI_SUMMARY=true, ask Claude to restructure raw doc per DOC_STYLE_INSTRUCTIONS. Else return as-is."""
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
            if m != model and model == fallback:
                break
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
doc_path = DOCS_DIR / "frontend-components.md"
doc_path.write_text(final_md, encoding="utf-8")
print("Generated docs:", doc_path)


def publish_to_confluence(md_path: Path) -> None:
    """Create a Confluence page from the generated markdown. Requires env: CONFLUENCE_BASE_URL, CONFLUENCE_USER_EMAIL, CONFLUENCE_API_TOKEN, CONFLUENCE_PARENT_PAGE_ID."""
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
    # Get parent page to obtain space key
    r = requests.get(
        f"{api_base}/content/{parent_id}",
        params={"expand": "space"},
        auth=auth,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    space_key = r.json()["space"]["key"]
    # Convert markdown to HTML for Confluence storage
    md_text = md_path.read_text(encoding="utf-8")
    html = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    storage_value = html if html.strip().startswith("<") else f"<p>{html}</p>"
    title = "Frontend Components"
    body_payload = {
        "storage": {"value": storage_value, "representation": "storage"}
    }
    # Check for existing page with same title under parent
    r = requests.get(
        f"{api_base}/content/{parent_id}/child/page",
        auth=auth,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    existing = next(
        (p for p in r.json().get("results", []) if p.get("title") == title),
        None,
    )
    if existing:
        page_id = existing["id"]
        r = requests.get(
            f"{api_base}/content/{page_id}",
            params={"expand": "body.storage,version"},
            auth=auth,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        version = r.json()["version"]["number"] + 1
        r = requests.put(
            f"{api_base}/content/{page_id}",
            json={"id": page_id, "type": "page", "title": title, "version": {"number": version}, "body": body_payload},
            auth=auth,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        print("Confluence: page updated at", r.json().get("_links", {}).get("webui", ""))
    else:
        payload = {
            "type": "page",
            "title": title,
            "ancestors": [{"id": parent_id}],
            "space": {"key": space_key},
            "body": body_payload,
        }
        r = requests.post(
            f"{api_base}/content",
            json=payload,
            auth=auth,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        print("Confluence: page created at", r.json().get("_links", {}).get("webui", ""))


publish_to_confluence(doc_path)
