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

files = subprocess.check_output(
    ["git", "-C", "flash-front", "diff", "--name-only", "HEAD~1..HEAD"],
).decode().splitlines()

print("Frontend changes:")
for f in files:
    print("-", f)

doc_path = DOCS_DIR / "frontend-components.md"
doc_path.write_text(
    "# Frontend Components\n\n"
    "## Button\n"
    "- Source: `src/Button.tsx`\n"
    "- Purpose: Reusable UI button\n"
)

print("Generated docs:", doc_path)
