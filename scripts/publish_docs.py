import os
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--files", required=True)
args = parser.parse_args()

files = args.files.split()

print("\n=== CONFLUENCE PAYLOAD PREVIEW ===\n")

for f in files:
    content = Path(f).read_text()
    print(f"Page title: {Path(f).stem.replace('-', ' ').title()}")
    print("Parent page ID:", os.getenv("CONFLUENCE_PARENT_PAGE_ID"))
    print("Body:")
    print(content)
    print("\n---\n")
