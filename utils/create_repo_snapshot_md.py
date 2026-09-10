#!/usr/bin/env python3
"""
Create a complete Markdown snapshot of a GitHub repository branch using git clone.

Features:
- Clones the repo into a temporary directory
- Checks out exactly one branch (default: main)
- Recursively walks the working tree locally
- Skips binary files
- Preserves directory nesting using nested Markdown headings
- Uses language-specific code fences where possible
- Deletes the temporary clone after the snapshot is written

Requirements:
- git must be installed and available on PATH
- Python 3.9+
- No third-party Python dependencies required

Usage:
    python snapshot_repo.py https://github.com/user/repo
    python snapshot_repo.py https://github.com/user/repo dev_plet_rusle
    python snapshot_repo.py https://github.com/user/repo -o snapshot.md
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".exe", ".dll", ".so", ".dylib", ".class", ".o", ".a",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".woff", ".woff2", ".ttf", ".otf",
    ".jar", ".war", ".ear", ".bin", ".pyc", ".pyo",
    ".gpkg", ".sqlite", ".db", ".dat",
}

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".json": "json",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".xml": "xml",
    ".txt": "text",
}


def normalize_repo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise ValueError("Only github.com URLs are supported.")

    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("Repo URL must look like https://github.com/user/repo")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    return f"https://github.com/{owner}/{repo}"


def get_default_branch_arg(args_branch: str | None) -> str:
    return args_branch if args_branch else "main"


def is_binary_path(path: Path) -> bool:
    _, ext = os.path.splitext(path.name.lower())
    return ext in BINARY_EXTENSIONS


def language_for_path(path: Path) -> str:
    _, ext = os.path.splitext(path.name.lower())
    return LANGUAGE_MAP.get(ext, "text")


def run(cmd: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    return result.stdout


def clone_repo(repo_url: str, target_dir: str) -> None:
    run(["git", "clone", "--quiet", repo_url, target_dir])


def checkout_branch(repo_dir: str, branch: str) -> None:
    # Try direct checkout first.
    try:
        run(["git", "checkout", "--quiet", branch], cwd=repo_dir)
        return
    except RuntimeError:
        pass

    # Try remote-tracking branch.
    run(["git", "checkout", "--quiet", "-b", branch, f"origin/{branch}"], cwd=repo_dir)


def list_files(repo_dir: str) -> list[Path]:
    files: list[Path] = []
    for p in Path(repo_dir).rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            files.append(p)
    return files


def read_text_file(path: Path) -> str | None:
    if is_binary_path(path):
        return None

    try:
        raw = path.read_bytes()
    except Exception:
        return None

    if b"\x00" in raw[:4096]:
        return None

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def heading_level_for_depth(depth: int) -> int:
    # Use increasing nesting: root file sections start at ###, deeper dirs get more #
    return min(6, 3 + depth)


def write_heading(out, text: str, level: int) -> None:
    level = max(1, min(6, level))
    out.write(f"{'#' * level} {text}\n\n")


def write_snapshot_header(out, repo_url: str, branch: str) -> None:
    out.write("# Complete Repository Code Snapshot\n\n")
    out.write("This document is a **complete code snapshot** of a single GitHub repository branch,\n")
    out.write("created from a local `git clone` and organized for readable archival/reference.\n\n")
    out.write(f"- Repository: {repo_url}\n")
    out.write(f"- Branch: `{branch}`\n")
    out.write("- Binary files: excluded\n")
    out.write("- Source: local clone of the remote repository\n\n")
    out.write("> Note: This snapshot includes all text-based files found in the checked-out branch.\n")
    out.write("> Large binary assets are intentionally omitted.\n\n")


def write_branch_snapshot(out, repo_dir: str, branch: str) -> None:
    files = sorted(list_files(repo_dir), key=lambda p: str(p).lower())
    write_heading(out, f"Branch: `{branch}`", 2)
    out.write(f"_Complete code snapshot for branch `{branch}`._\n\n")

    skipped: list[tuple[str, str]] = []
    included = 0
    current_dirs: list[str] = []

    for path in files:
        rel = path.relative_to(repo_dir)

        if is_binary_path(rel):
            skipped.append((str(rel), "binary extension"))
            continue

        content = read_text_file(path)
        if content is None:
            skipped.append((str(rel), "binary or undecodable content"))
            continue

        dir_parts = list(rel.parent.parts)
        if dir_parts == ["."]:
            dir_parts = []

        # Emit nested directory headings only when the directory path changes.
        common = 0
        while common < len(current_dirs) and common < len(dir_parts) and current_dirs[common] == dir_parts[common]:
            common += 1

        current_dirs = current_dirs[:common]

        for i in range(common, len(dir_parts)):
            current_dirs.append(dir_parts[i])
            depth = len(current_dirs)
            write_heading(out, f"Directory: `{Path(*current_dirs)}`", heading_level_for_depth(depth))

        file_depth = len(current_dirs) + 1
        write_heading(out, f"File: `{rel}`", heading_level_for_depth(file_depth))

        lang = language_for_path(rel)
        out.write(f"```{lang}\n")
        out.write(content.rstrip() + "\n")
        out.write("```\n\n")
        included += 1

    write_heading(out, "Branch summary", 3)
    out.write(f"- Included text files: {included}\n")
    out.write(f"- Skipped files: {len(skipped)}\n\n")

    if skipped:
        write_heading(out, "Skipped files", 4)
        for item, reason in skipped:
            out.write(f"- `{item}` — {reason}\n")
        out.write("\n")


def snapshot_repo(repo_url: str, branch: str, output_file: str) -> None:
    repo_url = normalize_repo_url(repo_url)

    with tempfile.TemporaryDirectory(prefix="repo_snapshot_") as tmpdir:
        clone_dir = os.path.join(tmpdir, "repo")
        print("Cloning repository into a temporary directory...")
        clone_repo(repo_url, clone_dir)

        print(f"Checking out branch: {branch}")
        try:
            checkout_branch(clone_dir, branch)
        except Exception as e:
            raise RuntimeError(f"Failed to checkout branch `{branch}`: {e}")

        with open(output_file, "w", encoding="utf-8") as out:
            write_snapshot_header(out, repo_url, branch)
            write_branch_snapshot(out, clone_dir, branch)

        print(f"Snapshot written to: {output_file}")
        print("Temporary clone deleted automatically.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a complete Markdown snapshot of a GitHub repo branch using git clone."
    )
    parser.add_argument(
        "repo",
        help="GitHub repo URL, e.g. https://github.com/user/repo or ...git"
    )
    parser.add_argument(
        "branch",
        nargs="?",
        default="main",
        help="Branch name to snapshot (default: main)"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="repo_snapshot.md",
        help="Output markdown file"
    )

    args = parser.parse_args()

    try:
        snapshot_repo(args.repo, args.branch, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()