import os
from datetime import datetime, timezone
from pathlib import Path

CONTEXT_DIR = ".fde"
CONTEXT_FILE = f"{CONTEXT_DIR}/context.md"


def read_file(repo_path: str, file_path: str) -> str:
    """Read the contents of a file in the repository.

    Args:
        repo_path: Absolute path to the repository root.
        file_path: Relative path to the file from repo root.

    Returns:
        The file contents as a string.
    """
    full_path = Path(repo_path) / file_path
    resolved = full_path.resolve()

    if not resolved.is_relative_to(Path(repo_path).resolve()):
        raise PermissionError(f"Access denied: {file_path} is outside the repository.")

    if not resolved.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    return resolved.read_text(encoding="utf-8", errors="replace")


def list_directory(repo_path: str, dir_path: str = ".", max_depth: int = 3) -> str:
    """List the directory tree of the repository.

    Args:
        repo_path: Absolute path to the repository root.
        dir_path: Relative path to list from. Defaults to root.
        max_depth: How deep to recurse.

    Returns:
        A formatted directory tree string.
    """
    root = (Path(repo_path) / dir_path).resolve()

    if not root.is_relative_to(Path(repo_path).resolve()):
        raise PermissionError(f"Access denied: {dir_path} is outside the repository.")

    if not root.is_dir():
        raise FileNotFoundError(f"Directory not found: {dir_path}")

    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".next", ".mypy_cache", ".ruff_cache"}
    lines: list[str] = []

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return

        dirs = [e for e in entries if e.is_dir() and e.name not in skip_dirs]
        files = [e for e in entries if e.is_file()]

        for f in files:
            lines.append(f"{prefix}{f.name}")

        for d in dirs:
            lines.append(f"{prefix}{d.name}/")
            _walk(d, prefix + "  ", depth + 1)

    lines.append(f"{root.name}/")
    _walk(root, "  ", 1)
    return "\n".join(lines)


def search_files(repo_path: str, pattern: str, file_extension: str | None = None) -> str:
    """Search for a text pattern across files in the repository.

    Args:
        repo_path: Absolute path to the repository root.
        pattern: Text to search for (case-insensitive).
        file_extension: Optional filter like '.py', '.ts'.

    Returns:
        Formatted search results showing file, line number, and matching line.
    """
    root = Path(repo_path).resolve()
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".next"}
    results: list[str] = []
    max_results = 50

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        for filename in filenames:
            if file_extension and not filename.endswith(file_extension):
                continue

            filepath = Path(dirpath) / filename
            rel_path = filepath.relative_to(root)

            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            for line_num, line in enumerate(content.splitlines(), start=1):
                if pattern.lower() in line.lower():
                    results.append(f"{rel_path}:{line_num}: {line.strip()}")
                    if len(results) >= max_results:
                        results.append(f"... (truncated at {max_results} results)")
                        return "\n".join(results)

    if not results:
        return f"No matches found for '{pattern}'."

    return "\n".join(results)


def write_file(repo_path: str, file_path: str, content: str) -> str:
    """Write content to a file in the repository. Creates parent directories if needed.

    Args:
        repo_path: Absolute path to the repository root.
        file_path: Relative path to the file from repo root.
        content: The content to write.

    Returns:
        Confirmation message.
    """
    full_path = Path(repo_path) / file_path
    resolved = full_path.resolve()

    if not resolved.is_relative_to(Path(repo_path).resolve()):
        raise PermissionError(f"Access denied: {file_path} is outside the repository.")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")

    return f"Successfully wrote {file_path} ({len(content)} chars)."


def read_context(repo_path: str) -> str | None:
    """Read the .fde/context.md file if it exists.

    Returns:
        The context file contents, or None if it doesn't exist.
    """
    context_path = Path(repo_path) / CONTEXT_FILE

    if not context_path.is_file():
        return None

    return context_path.read_text(encoding="utf-8", errors="replace")


def write_context(repo_path: str, content: str) -> str:
    """Write or update the .fde/context.md file.

    Args:
        repo_path: Absolute path to the repository root.
        content: The full context markdown content.

    Returns:
        Confirmation message.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"<!-- Auto-generated by FDE. Last updated: {timestamp} -->\n\n"
    return write_file(repo_path, CONTEXT_FILE, header + content)
