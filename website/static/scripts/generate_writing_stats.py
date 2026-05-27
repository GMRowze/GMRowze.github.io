#!/usr/bin/env python3
"""Generate sanitized static writing analytics JSON for Hugo widgets."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "website" / "static" / "data" / "writing"
WORD_RE = re.compile(r"\b[\w'’.-]+\b", re.UNICODE)
CHAPTER_RE = re.compile(r"(?:chapter|chap|ch)[_-]?(\d+|[xivxlcdm]+|xx)", re.IGNORECASE)


def run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"unreadable: {exc}"
    if raw.startswith(b"\x00GITCRYPT") or b"git-crypt" in raw[:128].lower():
        return None, "git-crypt locked"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "not utf-8 text; possibly encrypted"


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n") or text.startswith("---\r\n"):
        end = text.find("\n---", 4)
        if end != -1:
            front = text[4:end]
            body = text[text.find("\n", end + 1) + 1 :]
            return parse_yaml_like(front), body
    if text.startswith("+++\n") or text.startswith("+++\r\n"):
        end = text.find("\n+++", 4)
        if end != -1:
            front = text[4:end]
            body = text[text.find("\n", end + 1) + 1 :]
            if tomllib:
                try:
                    return tomllib.loads(front), body
                except tomllib.TOMLDecodeError:
                    pass
            return parse_yaml_like(front), body
    return {}, text


def parse_yaml_like(text: str) -> dict:
    data = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.+?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip('"').strip("'")
        if value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
        elif re.fullmatch(r"-?\d+", value):
            data[key] = int(value)
        else:
            data[key] = value
    return data


def count_words(markdown: str) -> int:
    markdown = re.sub(r"<!--.*?-->", " ", markdown, flags=re.DOTALL)
    markdown = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    markdown = re.sub(r"`[^`]*`", " ", markdown)
    markdown = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", markdown)
    markdown = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", markdown)
    markdown = re.sub(r"^[#>*\-\s]+", " ", markdown, flags=re.MULTILINE)
    return len([word for word in WORD_RE.findall(markdown) if any(ch.isalpha() for ch in word)])


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "untitled"


def roman_to_int(value: str) -> int | None:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for char in reversed(value.lower()):
        current = values.get(char)
        if not current:
            return None
        total += -current if current < previous else current
        previous = max(previous, current)
    return total or None


def infer_chapter(path: Path, front_matter: dict) -> tuple[int | None, bool]:
    is_appendix = bool(front_matter.get("appendix")) or "appendix" in path.stem.lower() or "annex" in path.stem.lower()
    chapter = front_matter.get("chapter") or front_matter.get("chapter_number")
    if isinstance(chapter, int):
        return chapter, is_appendix
    if isinstance(chapter, str) and chapter.isdigit():
        return int(chapter), is_appendix
    match = CHAPTER_RE.search(path.stem)
    if not match:
        return None, is_appendix
    token = match.group(1).lower()
    if token.isdigit():
        return int(token), is_appendix
    if token == "xx":
        return None, True
    return roman_to_int(token), is_appendix


def infer_project(path: Path, front_matter: dict) -> str | None:
    for key in ("project", "book", "series"):
        if front_matter.get(key):
            return slugify(str(front_matter[key]))
    parts = path.parts
    if "books" in parts:
        index = parts.index("books")
        if len(parts) > index + 2:
            return slugify(parts[index + 2])
        if len(parts) > index + 1:
            return slugify(parts[index + 1])
    return None


def infer_status(path: Path, front_matter: dict) -> str:
    status = str(front_matter.get("status") or front_matter.get("draft_status") or "").lower().strip()
    if status:
        return slugify(status)
    if "Published" in path.parts or "published" in path.parts:
        return "published"
    return "draft"


def is_marked_private(path: Path, front_matter: dict) -> bool:
    markers = {"private", "encrypted", "secret", "git-crypt"}
    if "Drafts" in path.parts or "drafts" in path.parts:
        return True
    for key in ("private", "encrypted", "sensitive"):
        if front_matter.get(key):
            return True
    return any(part.lower() in markers for part in path.parts)


def discover_markdown(scan_roots: list[Path]) -> list[Path]:
    ignored = {".git", "public", "node_modules", ".hugo_build.lock"}
    files = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if not path.is_file():
                continue
            if ignored.intersection(path.parts):
                continue
            files.append(path)
    return sorted(set(files))


def collect_content(scan_roots: list[Path], target_words: int, expected_chapters: int) -> tuple[dict, dict, list[dict]]:
    corpus = Counter()
    projects: dict[str, dict] = {}
    project_titles: dict[str, str] = {}
    unavailable = []

    for path in discover_markdown(scan_roots):
        text, error = read_text(path)
        relative = path.relative_to(ROOT).as_posix()
        if error:
            unavailable.append({"path": relative, "reason": error})
            continue

        front_matter, body = split_front_matter(text or "")
        if front_matter.get("writing_stats_exclude") or front_matter.get("stats_exclude"):
            continue
        project_id = infer_project(path, front_matter)
        status = infer_status(path, front_matter)
        words = count_words(body)
        if is_marked_private(path, front_matter):
            corpus["private_words"] += words

        if path.name == "_index.md" and project_id and front_matter.get("title"):
            project_titles[project_id] = str(front_matter["title"])

        if status == "published":
            corpus["published_words"] += words
        else:
            corpus["draft_words"] += words

        if not project_id or path.name == "_index.md":
            continue

        project = projects.setdefault(project_id, {
            "id": project_id,
            "title": project_titles.get(project_id, project_id.replace("-", " ").title()),
            "target_words_per_chapter": int(front_matter.get("target_words_per_chapter") or target_words),
            "expected_chapters": int(
                front_matter.get("expected_chapters")
                or front_matter.get("planned_chapters")
                or front_matter.get("chapter_count")
                or expected_chapters
            ),
            "chapters": [],
            "word_count": 0,
            "counts": {},
        })
        if project_id in project_titles:
            project["title"] = project_titles[project_id]
        chapter_number, is_appendix = infer_chapter(path, front_matter)
        title = front_matter.get("title") if front_matter.get("expose_title") else None
        project["chapters"].append({
            "index": 0,
            "number": chapter_number,
            "is_appendix": is_appendix,
            "status": status,
            "word_count": words,
            "path": relative,
            **({"title": title} if title else {}),
        })
        project["word_count"] += words
        project["counts"][status] = project["counts"].get(status, 0) + 1

    corpus["total_tracked_words"] = corpus["draft_words"] + corpus["published_words"]
    corpus["private_words"] = corpus["private_words"]
    corpus["private_unavailable_files"] = len(unavailable)
    corpus["locked_unavailable_files"] = len(unavailable)
    return dict(corpus), normalize_projects(projects), unavailable


def normalize_projects(projects: dict[str, dict]) -> dict:
    for project in projects.values():
        chapters = project["chapters"]
        numbered = [chapter["number"] for chapter in chapters if chapter["number"] and not chapter["is_appendix"]]
        max_chapter = max(numbered, default=0)
        expected_chapters = max(int(project.get("expected_chapters") or 0), max_chapter)
        by_number = {}
        appendices = []
        for chapter in chapters:
            if chapter["is_appendix"]:
                appendices.append(chapter)
            elif chapter["number"]:
                current = by_number.get(chapter["number"])
                if not current or status_rank(chapter["status"]) > status_rank(current["status"]):
                    by_number[chapter["number"]] = chapter
        normalized = []
        for number in range(1, expected_chapters + 1):
            chapter = by_number.get(number) or {
                "index": number,
                "number": number,
                "is_appendix": False,
                "status": "missing",
                "word_count": 0,
            }
            chapter["index"] = number
            normalized.append(chapter)
        for offset, appendix in enumerate(sorted(appendices, key=lambda item: item["path"]), start=1):
            appendix["index"] = expected_chapters + offset
            appendix["number"] = appendix.get("number") or offset
            normalized.append(appendix)
        project["chapters"] = normalized
        project["word_count"] = sum(chapter["word_count"] for chapter in normalized)
        project["counts"] = dict(Counter(chapter["status"] for chapter in normalized))
    return {
        "generated_at": now_iso(),
        "version": 1,
        "projects": sorted(projects.values(), key=lambda item: item["id"]),
    }


def status_rank(status: str) -> int:
    return {
        "missing": 0,
        "draft": 1,
        "complete": 2,
        "complete-unpublished": 2,
        "revised": 3,
        "published": 4,
    }.get(status, 1)


def word_delta_from_git(days: int) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    log = run_git(["log", f"--since={since}", "--format=%H%x09%cs", "--", "*.md"])
    by_date: dict[str, Counter] = defaultdict(Counter)
    for line in log.splitlines():
        if "\t" not in line:
            continue
        commit, date = line.split("\t", 1)
        patch = run_git(["show", "--format=", "--unified=0", "--no-ext-diff", commit, "--", "*.md"])
        text_added = 0
        text_removed = 0
        for patch_line in patch.splitlines():
            if patch_line.startswith("+++") or patch_line.startswith("---"):
                continue
            if patch_line.startswith("+"):
                text_added += count_words(patch_line[1:])
            elif patch_line.startswith("-"):
                text_removed += count_words(patch_line[1:])

        fallback_added, fallback_removed = local_commit_word_delta(commit)
        by_date[date]["words_added"] += max(text_added, fallback_added)
        by_date[date]["words_removed"] += max(text_removed, fallback_removed)

    daily = []
    for date in sorted(by_date):
        added = int(by_date[date]["words_added"])
        removed = int(by_date[date]["words_removed"])
        daily.append({
            "date": date,
            "words_added": added,
            "words_removed": removed,
            "net_words": added - removed,
        })
    return daily


def local_commit_word_delta(commit: str) -> tuple[int, int]:
    """Estimate encrypted/binary Markdown deltas from readable local files.

    git-crypt and path-only import commits can produce binary/no-text patches.
    When the current working tree has the file decrypted, use that local text as
    a conservative fallback for added files in commits that are ancestors of the
    current checkout. Deleted encrypted files cannot be safely reconstructed.
    """
    status = run_git(["show", "--format=", "--name-status", "--no-renames", commit, "--", "*.md"])
    added = 0
    removed = 0
    for line in status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        change, path_text = parts[0], parts[-1]
        path = ROOT / path_text
        if change == "A" and path.is_file():
            text, error = read_text(path)
            if not error and text is not None:
                _, body = split_front_matter(text)
                added += count_words(body)
        elif change == "D" and path.is_file():
            # The path exists locally after a case-only rename/import; avoid
            # treating old casing as removed manuscript text.
            continue
    return added, removed


def activity_from_daily(daily: list[dict]) -> dict:
    active_dates = {dt.date.fromisoformat(day["date"]) for day in daily if day["words_added"] or day["words_removed"]}
    if not active_dates:
        return {
            "current_streak_days": 0,
            "longest_streak_days": 0,
            "active_days_total": 0,
            "latest_writing_day": None,
        }

    today = dt.date.today()
    current = 0
    cursor = today
    while cursor in active_dates:
        current += 1
        cursor -= dt.timedelta(days=1)

    longest = 0
    streak = 0
    previous = None
    for date in sorted(active_dates):
        streak = streak + 1 if previous and date == previous + dt.timedelta(days=1) else 1
        longest = max(longest, streak)
        previous = date

    return {
        "current_streak_days": current,
        "longest_streak_days": longest,
        "active_days_total": len(active_dates),
        "latest_writing_day": max(active_dates).isoformat(),
    }


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Directory for stats.json and projects.json.")
    parser.add_argument("--scan-root", action="append", type=Path, help="Markdown root to scan. Can be used more than once.")
    parser.add_argument("--history-days", type=int, default=180, help="Days of git history to inspect for word deltas.")
    parser.add_argument("--target-words-per-chapter", type=int, default=3000)
    parser.add_argument("--expected-chapters", type=int, default=20, help="Default planned chapter count for book progress bars.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scan_roots = args.scan_root or [ROOT / "content", ROOT / "published", ROOT / "drafts"]
    scan_roots = [(path if path.is_absolute() else ROOT / path).resolve() for path in scan_roots]
    output = (args.output if args.output.is_absolute() else ROOT / args.output).resolve()

    corpus, projects, unavailable = collect_content(scan_roots, args.target_words_per_chapter, args.expected_chapters)
    daily = word_delta_from_git(args.history_days)
    stats = {
        "generated_at": now_iso(),
        "version": 1,
        "source_roots": [path.relative_to(ROOT).as_posix() for path in scan_roots if path.exists()],
        "corpus": corpus,
        "activity": activity_from_daily(daily),
        "daily": daily,
        "unavailable_files": unavailable,
    }

    write_json(output / "stats.json", stats)
    write_json(output / "projects.json", projects)
    print(f"Wrote {output / 'stats.json'}")
    print(f"Wrote {output / 'projects.json'}")
    if unavailable:
        print(f"Skipped {len(unavailable)} unavailable file(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
