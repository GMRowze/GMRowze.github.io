#!/usr/bin/env python3
"""Install a pre-commit hook that refreshes static writing analytics JSON."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / ".git" / "hooks" / "pre-commit"
MARKER_START = "# BEGIN writing stats dashboard"
MARKER_END = "# END writing stats dashboard"

HOOK_BLOCK = f"""\
{MARKER_START}
python3 website/static/scripts/generate_writing_stats.py
writing_stats_status=$?
if [ "$writing_stats_status" -ne 0 ]; then
  echo "writing stats generation failed; aborting commit" >&2
  exit "$writing_stats_status"
fi

if ! git diff --quiet -- website/static/data/writing/stats.json website/static/data/writing/projects.json; then
  git add website/static/data/writing/stats.json website/static/data/writing/projects.json
  echo "updated writing analytics JSON and added it to this commit"
fi
{MARKER_END}
"""


def install() -> int:
    if not (ROOT / ".git").exists():
        print("No .git directory found; hook was not installed.")
        return 1

    existing = HOOK.read_text(encoding="utf-8") if HOOK.exists() else ""
    if MARKER_START in existing and MARKER_END in existing:
        before, rest = existing.split(MARKER_START, 1)
        _, after = rest.split(MARKER_END, 1)
        content = before.rstrip() + "\n\n" + HOOK_BLOCK + after.lstrip()
    else:
        shebang = "#!/bin/sh\n\n"
        body = existing
        if existing.startswith("#!"):
            first_line, _, remainder = existing.partition("\n")
            shebang = first_line + "\n\n"
            body = remainder.lstrip()
        content = shebang + HOOK_BLOCK + ("\n" + body if body else "")

    HOOK.write_text(content, encoding="utf-8")
    mode = HOOK.stat().st_mode
    HOOK.chmod(mode | 0o111)
    print(f"Installed writing stats pre-commit hook at {HOOK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(install())
