import hashlib
import re
from pathlib import Path

_PROPERTY_RE = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*)::\s*(.*)$')
_INLINE_TAG_RE = re.compile(r'(?<!\w)#([a-zA-Z][a-zA-Z0-9_/-]*)')

# Only index these top-level subdirectories within a graph root.
_INDEXABLE_SUBDIRS = {"pages", "journals"}


def is_indexable(path: Path, graph_root: Path) -> bool:
    try:
        rel = path.relative_to(graph_root)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in _INDEXABLE_SUBDIRS


def _page_name(path: Path, graph_root: Path) -> str:
    rel = path.relative_to(graph_root)
    subdir = rel.parts[0]
    stem = path.stem
    if subdir == "journals":
        # File format is yyyy_MM_dd; title format is yyyy-MM-dd.
        return "journals/" + stem.replace("_", "-")
    # Triple-lowbar encodes namespace separators: "Projects___My Plan" → "Projects/My Plan"
    return stem.replace("___", "/")


def parse_page(path: Path, graph_root: Path, graph: str) -> dict | None:
    """Parse one Logseq .md file. Returns None if it should not be indexed."""
    if not is_indexable(path, graph_root):
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Logseq property drawer: consecutive `key:: value` lines at the top of the file.
    properties: dict[str, str] = {}
    for line in content.splitlines():
        m = _PROPERTY_RE.match(line)
        if m:
            properties[m.group(1)] = m.group(2).strip()
        elif line.strip():
            break  # first non-empty, non-property line ends the drawer

    # Tags from the tags:: property
    raw_tags = properties.get("tags", "")
    tags: list[str] = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

    # Inline #tags (deduplicated, property tags come first)
    seen = set(tags)
    for tag in _INLINE_TAG_RE.findall(content):
        if tag not in seen:
            tags.append(tag)
            seen.add(tag)

    lines = content.splitlines()
    block_count = sum(1 for ln in lines if re.match(r"^\s*-\s", ln))
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return {
        "graph": graph,
        "page_name": _page_name(path, graph_root),
        "file_path": str(path),
        "content": content,
        "properties": properties,
        "tags": tags or None,
        "block_count": block_count,
        "content_hash": content_hash,
    }
