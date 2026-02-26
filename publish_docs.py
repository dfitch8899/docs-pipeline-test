"""
Publish Markdown docs to Confluence. Optional: prepend AI summary when OPENAI_API_KEY + USE_AI_SUMMARY set.
"""
import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import markdown
import requests

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def confluence_session() -> requests.Session:
    base = env("CONFLUENCE_BASE_URL").rstrip("/")
    user = env("CONFLUENCE_USER_EMAIL")
    token = env("CONFLUENCE_API_TOKEN")
    if not all([base, user, token]):
        raise SystemExit("Set CONFLUENCE_BASE_URL, CONFLUENCE_USER_EMAIL, CONFLUENCE_API_TOKEN")
    s = requests.Session()
    s.auth = (user, token)
    s.headers["Accept"] = "application/json"
    s.headers["Content-Type"] = "application/json"
    s.base = base
    return s


def get_parent_page(sess: requests.Session) -> tuple[str, str]:
    """Return (space_id, parent_id)."""
    pid = env("CONFLUENCE_PARENT_PAGE_ID")
    if not pid:
        raise SystemExit("Set CONFLUENCE_PARENT_PAGE_ID")
    r = sess.get(f"{sess.base}/wiki/api/v2/pages/{pid}")
    r.raise_for_status()
    data = r.json()
    return data["spaceId"], data["id"]


def find_page_by_title(sess: requests.Session, space_id: str, parent_id: str, title: str) -> str | None:
    """Return page id if a child of parent with given title exists."""
    r = sess.get(
        f"{sess.base}/wiki/api/v2/pages",
        params={"space-id": space_id, "title": title, "limit": 1},
    )
    r.raise_for_status()
    results = r.json().get("results") or []
    for p in results:
        if p.get("parentId") == parent_id and p.get("title") == title:
            return p["id"]
    return None


def md_to_storage_html(md: str) -> str:
    html = markdown.markdown(md, extensions=["extra", "codehilite"])
    return f'<p>{html}</p>' if not html.strip().startswith("<") else html


def ai_format_document(title: str, text: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return text
    key = env("OPENAI_API_KEY")
    if not key:
        return text
    client = OpenAI(api_key=key)
    truncated = text[:20000]
    system_prompt = (
        "You are a senior technical writer. Rewrite the provided engineering markdown into a "
        "clear Confluence-ready architecture/spec document.\n"
        "Return markdown only.\n"
        "Use this section structure and headings in this exact order:\n"
        "1) Overview\n"
        "2) High-Level Architecture\n"
        "3) Technology Stack\n"
        "4) Repository Structure\n"
        "5) Request/Execution Flow\n"
        "6) Source of Truth and Ownership\n"
        "7) CI / CD Flow\n"
        "8) Important Rules (Do / Do Not)\n"
        "9) FAQ\n"
        "10) Summary\n"
        "Style requirements:\n"
        "- Keep it practical and engineering-focused.\n"
        "- Preserve important technical details, file paths, and key constraints.\n"
        "- Use bullet points and short numbered flows.\n"
        "- Add short code blocks only when needed.\n"
        "- If source material lacks a section, add 'Not specified yet.' for that section.\n"
        "- Do not invent product decisions or fake implementation details."
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Document title: {title}\n\nSource markdown:\n{truncated}",
            },
        ],
        max_tokens=1800,
    )
    formatted = (resp.choices[0].message.content or "").strip()
    return formatted if formatted else text


def page_title_from_path(path: str) -> str:
    name = Path(path).stem
    return re.sub(r"[-_]+", " ", name).title()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=str, default="", help="Space-separated paths to .md files")
    args = parser.parse_args()
    paths = [p.strip() for p in args.files.split() if p.strip()]
    if not paths:
        docs_dir = Path("docs")
        if docs_dir.is_dir():
            paths = [str(f) for f in docs_dir.rglob("*.md")]
        if not paths:
            print("No doc files to publish.")
            return

    use_ai = env("USE_AI_SUMMARY", "false").lower() in ("1", "true", "yes")
    sess = confluence_session()
    space_id, parent_id = get_parent_page(sess)

    for filepath in paths:
        path = Path(filepath)
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        title = page_title_from_path(filepath)
        raw = path.read_text(encoding="utf-8", errors="replace")
        body_md = raw
        if use_ai and env("OPENAI_API_KEY"):
            body_md = ai_format_document(title, raw)
        storage_html = md_to_storage_html(body_md)
        existing_id = find_page_by_title(sess, space_id, parent_id, title)

        if existing_id:
            r = sess.get(f"{sess.base}/wiki/api/v2/pages/{existing_id}")
            r.raise_for_status()
            version = r.json()["version"]["number"]
            r = sess.put(
                f"{sess.base}/wiki/api/v2/pages/{existing_id}",
                json={
                    "id": existing_id,
                    "status": "current",
                    "title": title,
                    "body": {"representation": "storage", "value": storage_html},
                    "version": {"number": version + 1, "message": f"Docs sync: {path.name}"},
                },
            )
            r.raise_for_status()
            print(f"Updated: {title} ({r.json().get('_links', {}).get('webui', '')})")
        else:
            r = sess.post(
                f"{sess.base}/wiki/api/v2/pages",
                json={
                    "spaceId": space_id,
                    "status": "current",
                    "title": title,
                    "parentId": parent_id,
                    "body": {"representation": "storage", "value": storage_html},
                },
            )
            r.raise_for_status()
            print(f"Created: {title} ({r.json().get('_links', {}).get('webui', '')})")


if __name__ == "__main__":
    main()
