import os
import subprocess
from pathlib import Path
# -----------------------------
# Backend changes
# -----------------------------
try:
    backend_files = subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD~1..HEAD"]
    ).decode().splitlines()
except subprocess.CalledProcessError:
    backend_files = []

# Ignore GitHub workflow changes
backend_files = [f for f in backend_files if not f.startswith(".github/")]

print("Backend changes:")
for f in backend_files:
    print("-", f)

# -----------------------------
# Frontend changes
# -----------------------------
FRONTEND_REPO = "AI-OWL/flash-front.git"
TOKEN = os.environ.get("FRONTEND_REPO_TOKEN")

if not TOKEN:
    raise RuntimeError("FRONTEND_REPO_TOKEN environment variable is missing")

clone_url = f"https://x-access-token:{TOKEN}@github.com/{FRONTEND_REPO}"

# Clone frontend repo if not already cloned
if not Path("flash-front").exists():
    subprocess.run(["git", "clone", clone_url], check=True)

# Read last processed commit
state_file = Path("docs-bot/last_frontend_commit.txt")
last_commit = state_file.read_text().strip()

# Get current HEAD
current_commit = subprocess.check_output(
    ["git", "-C", "flash-front", "rev-parse", "HEAD"]
).decode().strip()

# Get diff
frontend_files = subprocess.check_output(
    ["git", "-C", "flash-front", "diff", "--name-only", f"{last_commit}..HEAD"]
).decode().splitlines()

print("Frontend changes:")
for f in frontend_files:
    print("-", f)

# Save new commit hash
state_file.write_text(current_commit)
