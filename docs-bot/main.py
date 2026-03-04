import os
import subprocess
from pathlib import Path

DOCS_DIR = Path("docs")
DOCS_DIR.mkdir(exist_ok=True)

FRONTEND_REPO = "dfitch8899/flash-front-demo"
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

print("Frontend files found:")
for f in files:
    print("-", f)

doc_path = DOCS_DIR / "frontend-components.md"
lines = ["# Frontend Components\n", f"_Source repo: `{FRONTEND_REPO}`_\n\n"]

for f in files:
    file_path = Path("flash-front") / f
    if not file_path.exists() or not file_path.is_file():
        continue

    lines.append(f"## `{f}`\n")

    # try to read as text, skip binaries
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        lines.append("_Binary or unreadable file, skipped._\n\n")
        continue

    suffix = file_path.suffix.lstrip(".")
    lines.append(f"```{suffix}\n")
    lines.append(content)
    lines.append("```\n\n")

doc_path.write_text("".join(lines))
print("Generated docs:", doc_path)
