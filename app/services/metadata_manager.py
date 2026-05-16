import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

# Anchor paths to this file's location — works regardless of where uvicorn is launched
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
METADATA_FILE = os.path.normpath(os.path.join(_BASE_DIR, "..", "..", "metadata", "files.json"))
METADATA_TMP  = METADATA_FILE + ".tmp"

os.makedirs(os.path.dirname(METADATA_FILE), exist_ok=True)

# ============================================================
# LOAD / SAVE (atomic)
# ============================================================

def load_metadata() -> list[dict]:
    """
    Load all metadata records. Returns [] on missing/corrupt file.
    """
    if not os.path.exists(METADATA_FILE):
        return []

    try:
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_metadata(record: dict) -> None:
    """
    Append one record to the metadata store.
    Adds an 'uploaded_at' timestamp automatically.
    Uses an atomic write (tmp file → rename) to avoid corruption on crash.
    """
    record["uploaded_at"] = datetime.now(timezone.utc).isoformat()

    existing = load_metadata()
    existing.append(record)

    # Write to temp file first, then atomically replace
    with open(METADATA_TMP, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=4, ensure_ascii=False)

    shutil.move(METADATA_TMP, METADATA_FILE)


def update_metadata(original_filename: str, updates: dict) -> bool:
    """
    Update fields of an existing record by original_filename.
    Returns True if a record was found and updated.
    """
    records = load_metadata()
    updated = False

    for record in records:
        if record.get("original_filename", "").lower() == original_filename.lower():
            record.update(updates)
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated = True
            break

    if updated:
        with open(METADATA_TMP, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=4, ensure_ascii=False)
        shutil.move(METADATA_TMP, METADATA_FILE)

    return updated


def delete_by_filename(original_filename: str) -> bool:
    """
    Remove a record by original_filename. Returns True if deleted.
    """
    records = load_metadata()
    before = len(records)
    records = [
        r for r in records
        if r.get("original_filename", "").lower() != original_filename.lower()
    ]

    if len(records) == before:
        return False

    with open(METADATA_TMP, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=4, ensure_ascii=False)
    shutil.move(METADATA_TMP, METADATA_FILE)
    return True


# ============================================================
# DUPLICATE DETECTION
# ============================================================

def find_duplicate(
    file_hash: Optional[str] = None,
    content_hash: Optional[str] = None,
    image_hash: Optional[str] = None,
    original_filename: Optional[str] = None,
    min_content_length: int = 50,
) -> Optional[dict]:
    """
    Check if a file already exists in metadata using any of:
      - Same original filename (case-insensitive)
      - Same file hash (byte-identical)
      - Same content hash (same extracted text, e.g. re-exported doc)
      - Same image hash (visually identical image, phash exact match)

    Returns the matching metadata record, or None.

    The router should call this once instead of implementing its own loop.
    """
    records = load_metadata()

    for item in records:

        # 1. Same original filename
        if (
            original_filename
            and item.get("original_filename", "").lower() == original_filename.lower()
        ):
            return {**item, "_duplicate_reason": "filename"}

        # 2. Byte-identical file
        if file_hash and item.get("file_hash") == file_hash:
            return {**item, "_duplicate_reason": "file_bytes"}

        # 3. Same extracted content (skip very short content to avoid false positives)
        if (
            content_hash
            and item.get("content_hash") == content_hash
            and len(content_hash) > min_content_length
        ):
            return {**item, "_duplicate_reason": "content"}

        # 4. Visually identical image (exact phash match here; fuzzy match in router)
        if image_hash and item.get("image_hash") == image_hash:
            return {**item, "_duplicate_reason": "image_hash"}

    return None


# ============================================================
# SEARCH
# ============================================================

def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def search_metadata(query: str) -> list[dict]:
    """
    Full-text search across:
      original_filename, new_filename, category, file_kind, summary.
    Returns matching records sorted by upload date (newest first).
    """
    records = load_metadata()
    query_norm = normalize_text(query)
    results = []

    for item in records:
        searchable = normalize_text(" ".join([
            item.get("original_filename", ""),
            item.get("new_filename", ""),
            item.get("category", ""),
            item.get("file_kind", ""),
            item.get("summary", ""),
        ]))

        if query_norm in searchable:
            results.append(item)

    # Sort newest first
    results.sort(
        key=lambda r: r.get("uploaded_at", ""),
        reverse=True
    )

    return results


# ============================================================
# UTILITY QUERIES
# ============================================================

def get_all_categories() -> list[str]:
    """Return a sorted list of unique category names in the store."""
    records = load_metadata()
    return sorted({r.get("category", "Unknown") for r in records})


def get_records_by_category(category: str) -> list[dict]:
    """Return all records belonging to a given category."""
    records = load_metadata()
    return [r for r in records if r.get("category", "").lower() == category.lower()]