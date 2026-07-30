from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MIB = 1024 * 1024
DEFAULT_VIEW_LIMIT = 3 * MIB
DEFAULT_EDIT_LIMIT = 8 * MIB
SNIFF_BYTES = 8192

# F3 and F4 are deliberately limited to formats that are normally plain text.
# Images, movies, archives, executables, Office documents, and PDFs must be
# opened through Preview or the Windows default application instead.
SAFE_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".rst",
        ".csv",
        ".tsv",
        ".log",
        ".json",
        ".jsonl",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".properties",
        ".env",
        ".py",
        ".pyw",
        ".ps1",
        ".psm1",
        ".psd1",
        ".bat",
        ".cmd",
        ".sh",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".scss",
        ".less",
        ".html",
        ".htm",
        ".sql",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".java",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".tex",
        ".diff",
        ".patch",
    }
)

SAFE_EXTENSIONLESS_NAMES = frozenset(
    {
        "readme",
        "license",
        "licence",
        "changelog",
        "changes",
        "authors",
        "contributors",
        "copying",
        "makefile",
        "dockerfile",
        ".env",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
    }
)


@dataclass(frozen=True)
class SafeTextDecision:
    """Result of the bounded preflight check used by F3 and F4."""

    allowed: bool
    reason: str
    size: int | None = None
    limit: int | None = None


def _has_binary_signature(sample: bytes) -> bool:
    """Reject obvious binary content without decoding or reading the file."""
    if not sample:
        return False

    # UTF-16 text legitimately contains many NUL bytes.
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    if b"\x00" in sample:
        return True

    control_count = sum(
        byte < 32 and byte not in {9, 10, 12, 13}
        for byte in sample
    )
    return control_count / len(sample) > 0.08


def inspect_safe_text_file(
    path: Path,
    *,
    max_bytes: int,
) -> SafeTextDecision:
    """Perform a fast, bounded safety check before F3 or F4 opens a file."""
    try:
        stat_result = path.stat()
    except OSError:
        return SafeTextDecision(False, "unreadable")

    if not path.is_file():
        return SafeTextDecision(False, "not_file")

    suffix = path.suffix.lower()
    name = path.name.casefold()
    if (
        suffix not in SAFE_TEXT_EXTENSIONS
        and name not in SAFE_EXTENSIONLESS_NAMES
    ):
        return SafeTextDecision(
            False,
            "unsupported_type",
            size=stat_result.st_size,
            limit=max_bytes,
        )

    if stat_result.st_size > max_bytes:
        return SafeTextDecision(
            False,
            "too_large",
            size=stat_result.st_size,
            limit=max_bytes,
        )

    try:
        with path.open("rb") as stream:
            sample = stream.read(SNIFF_BYTES)
    except OSError:
        return SafeTextDecision(
            False,
            "unreadable",
            size=stat_result.st_size,
            limit=max_bytes,
        )

    if _has_binary_signature(sample):
        return SafeTextDecision(
            False,
            "binary_content",
            size=stat_result.st_size,
            limit=max_bytes,
        )

    return SafeTextDecision(
        True,
        "safe_text",
        size=stat_result.st_size,
        limit=max_bytes,
    )


def format_file_size(size: int | None) -> str:
    if size is None:
        return "unknown size"
    if size < 1024:
        return f"{size:,} B"
    if size < MIB:
        return f"{size / 1024:,.1f} KB"
    return f"{size / MIB:,.1f} MB"
