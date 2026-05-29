#!/usr/bin/env python3
"""Static Hugo writing workflow for draft, beta, and public chapters."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


ROOT = Path(__file__).resolve().parents[3]
DRAFTS = ROOT / "drafts"
PUBLISHED = ROOT / "published"
MORE_MARKER = "<!-- MORE -->"
ITERATIONS = 200_000
PRIVATE_FRONTMATTER_KEYS = {"password", "beta_password", "secret", "passphrase"}
ENCRYPTED_BLOCK_RE = re.compile(
    r"{{<\s*encrypted-block\s*>}}\s*(?P<payload>{.*?})\s*{{<\s*/encrypted-block\s*>}}",
    re.DOTALL,
)


class WriterError(Exception):
    pass


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise WriterError(f"cannot read {path}: {exc}") from exc


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def split_frontmatter(text: str) -> tuple[str, dict, str]:
    if text.startswith("---\n") or text.startswith("---\r\n"):
        newline = "\r\n" if text.startswith("---\r\n") else "\n"
        end = text.find(f"{newline}---", 4)
        if end != -1:
            raw = text[4:end]
            body_start = text.find(newline, end + len(newline) + 3)
            body = text[body_start + len(newline) :] if body_start != -1 else ""
            return "yaml", parse_yaml(raw), body
    if text.startswith("+++\n") or text.startswith("+++\r\n"):
        raise WriterError("TOML frontmatter is not yet supported by writer; use YAML frontmatter for beta chapters")
    return "yaml", {}, text


def parse_yaml(raw: str) -> dict:
    if yaml:
        loaded = yaml.safe_load(raw) or {}
        if not isinstance(loaded, dict):
            raise WriterError("frontmatter must be a mapping")
        return loaded

    data = {}
    for line in raw.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if match:
            key, value = match.groups()
            data[key] = value.strip().strip('"').strip("'")
    return data


def dump_frontmatter(frontmatter: dict) -> str:
    if yaml:
        return yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    lines = []
    for key, value in frontmatter.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, str) else str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def render_markdown(frontmatter: dict, body: str) -> str:
    return f"---\n{dump_frontmatter(frontmatter)}\n---\n\n{body.lstrip()}"


def status_of(frontmatter: dict) -> str:
    return str(frontmatter.get("status") or "draft").strip().lower()


def public_path_for(draft_path: Path) -> Path:
    draft_path = draft_path.resolve()
    try:
        relative = draft_path.relative_to(DRAFTS)
    except ValueError as exc:
        raise WriterError(f"{draft_path} is not inside {DRAFTS}") from exc
    return PUBLISHED / relative


def resolve_input_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    path = Path(normalized).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([ROOT / path, ROOT / "website" / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if "/" not in normalized:
        collapsed = normalized.lower()
        matches = [
            candidate
            for root in (DRAFTS, PUBLISHED)
            for candidate in root.rglob("*.md")
            if candidate.relative_to(ROOT).as_posix().replace("/", "").lower() == collapsed
        ]
        if len(matches) == 1:
            return matches[0]
    return candidates[0]


def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_markdown(markdown: str, password: str) -> dict:
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(iv, markdown.encode("utf-8"), None)
    return {
        "version": 1,
        "kdf": "PBKDF2",
        "hash": "SHA-256",
        "iterations": ITERATIONS,
        "salt": b64(salt),
        "iv": b64(iv),
        "ciphertext": b64(ciphertext),
    }


def validate_payload(payload: dict) -> list[str]:
    errors = []
    expected = {
        "version": 1,
        "kdf": "PBKDF2",
        "hash": "SHA-256",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            errors.append(f"{key} must be {value!r}")
    iterations = payload.get("iterations")
    if not isinstance(iterations, int) or iterations < 100_000:
        errors.append("iterations must be an integer >= 100000")
    for key in ("salt", "iv", "ciphertext"):
        if not isinstance(payload.get(key), str):
            errors.append(f"{key} must be a base64 string")
            continue
        try:
            raw = unb64(payload[key])
        except Exception:
            errors.append(f"{key} is not valid base64")
            continue
        if key == "salt" and len(raw) < 16:
            errors.append("salt must be at least 16 bytes")
        if key == "iv" and len(raw) != 12:
            errors.append("iv must be 12 bytes for AES-GCM")
    return errors


def public_frontmatter(frontmatter: dict, status: str) -> dict:
    cleaned = {key: value for key, value in frontmatter.items() if key not in PRIVATE_FRONTMATTER_KEYS}
    cleaned["status"] = status
    return cleaned


def plain_summary(markdown: str, limit: int = 240) -> str:
    text = re.sub(r"<!--.*?-->", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[#>*\-\s]+", " ", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "..."


def command_beta(path: Path) -> Path:
    kind, frontmatter, body = split_frontmatter(read_text(path))
    if kind != "yaml":
        raise WriterError("only YAML frontmatter is supported")
    if status_of(frontmatter) != "beta":
        raise WriterError(f"{path} must have status: beta")
    password = frontmatter.get("password")
    if not password:
        raise WriterError(f"{path} must have a password field for beta generation")
    if MORE_MARKER not in body:
        raise WriterError(f"{path} is beta but is missing {MORE_MARKER}")

    preview, protected = body.split(MORE_MARKER, 1)
    payload = encrypt_markdown(protected.strip() + "\n", str(password))
    shortcode = "{{< encrypted-block >}}\n" + json.dumps(payload, indent=2) + "\n{{< /encrypted-block >}}\n"
    beta_frontmatter = public_frontmatter(frontmatter, "beta")
    beta_frontmatter.setdefault("description", plain_summary(preview))
    output = render_markdown(beta_frontmatter, preview.rstrip() + "\n\n" + shortcode)
    destination = public_path_for(path)
    write_text(destination, output)
    return destination


def command_publish(path: Path, delete_draft: bool = False) -> Path:
    _, frontmatter, body = split_frontmatter(read_text(path))
    body = body.replace(MORE_MARKER, "").strip() + "\n"
    body = ENCRYPTED_BLOCK_RE.sub("", body).strip() + "\n"
    destination = public_path_for(path) if path.resolve().is_relative_to(DRAFTS) else path
    write_text(destination, render_markdown(public_frontmatter(frontmatter, "public"), body))
    if delete_draft and path.resolve().is_relative_to(DRAFTS):
        path.unlink()
    return destination


def parse_encrypted_blocks(path: Path, text: str) -> list[tuple[dict | None, str | None]]:
    blocks = []
    for match in ENCRYPTED_BLOCK_RE.finditer(text):
        raw = match.group("payload")
        try:
            blocks.append((json.loads(raw), None))
        except json.JSONDecodeError as exc:
            blocks.append((None, f"invalid JSON payload: {exc}"))
    return blocks


def command_check() -> int:
    errors = []
    for path in sorted(DRAFTS.rglob("*.md")):
        try:
            _, frontmatter, body = split_frontmatter(read_text(path))
        except WriterError as exc:
            errors.append(str(exc))
            continue
        if status_of(frontmatter) != "beta":
            continue
        if not frontmatter.get("password"):
            errors.append(f"{path}: beta draft is missing password")
        if MORE_MARKER not in body:
            errors.append(f"{path}: beta draft is missing {MORE_MARKER}")

    for path in sorted(PUBLISHED.rglob("*.md")):
        try:
            text = read_text(path)
        except WriterError as exc:
            errors.append(str(exc))
            continue
        _, frontmatter, body = split_frontmatter(text)
        leaked = sorted(PRIVATE_FRONTMATTER_KEYS.intersection(frontmatter))
        if leaked:
            errors.append(f"{path}: private frontmatter leaked: {', '.join(leaked)}")
        blocks = parse_encrypted_blocks(path, body)
        if status_of(frontmatter) == "beta" and not blocks:
            errors.append(f"{path}: status beta but no encrypted-block shortcode found")
        if status_of(frontmatter) == "public" and blocks:
            errors.append(f"{path}: status public should not contain encrypted blocks")
        for payload, error in blocks:
            if error:
                errors.append(f"{path}: {error}")
                continue
            for payload_error in validate_payload(payload or {}):
                errors.append(f"{path}: encrypted payload invalid: {payload_error}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("writer check: ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="writer", description="Generate static Hugo beta and public writing pages.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    beta = subparsers.add_parser("beta", help="Generate a beta page under published/")
    beta.add_argument("path")

    publish = subparsers.add_parser("publish", help="Generate a fully public page")
    publish.add_argument("path")
    publish.add_argument("--delete-draft", action="store_true")

    subparsers.add_parser("check", help="Validate beta/public workflow files")
    return parser


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "beta":
            destination = command_beta(resolve_input_path(args.path))
            print(f"Wrote {display_path(destination)}")
            return 0
        if args.command == "publish":
            destination = command_publish(resolve_input_path(args.path), args.delete_draft)
            print(f"Wrote {display_path(destination)}")
            return 0
        if args.command == "check":
            return command_check()
    except WriterError as exc:
        print(f"writer: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
