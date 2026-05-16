from fastapi import APIRouter, UploadFile, File, Query
import os
import re
import hashlib
import json
from collections import Counter
from PIL import Image
import imagehash
from fastapi.responses import FileResponse
from app.utils.logger import logger
from app.services.file_processor import extract_text
from app.services.gemini_service import ask_groq, analyze_image
from app.services.metadata_manager import (
    save_metadata,
    load_metadata,
    search_metadata,
)

router = APIRouter()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.normpath(os.path.join(_BASE_DIR, "..", "..", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =====================================================
# FILE TYPE REGISTRY
# Centralised — add new extensions here only
# =====================================================
IMAGE_EXTENSIONS   = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
VIDEO_EXTENSIONS   = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}
AUDIO_EXTENSIONS   = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}
DATA_EXTENSIONS    = {".csv", ".tsv", ".json", ".parquet", ".xlsx", ".xls"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".ppt"}
CODE_EXTENSIONS    = {".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".rs"}

def get_file_kind(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:    return "image"
    if ext in VIDEO_EXTENSIONS:    return "video"
    if ext in AUDIO_EXTENSIONS:    return "audio"
    if ext in DATA_EXTENSIONS:     return "data"
    if ext in DOCUMENT_EXTENSIONS: return "document"
    if ext in CODE_EXTENSIONS:     return "code"
    return "other"


# =====================================================
# HASH HELPERS
# Fast: size + partial hash for large files (videos etc.)
# Full SHA-256 only for small files (< 50 MB)
# =====================================================
LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB

def generate_file_hash(file_path: str) -> str:
    """
    For small files: full SHA-256.
    For large files: SHA-256 of (file_size + first 1MB + last 1MB).
    This prevents freezing the server on large video uploads.
    """
    file_size = os.path.getsize(file_path)
    sha256 = hashlib.sha256()
    sha256.update(str(file_size).encode())

    with open(file_path, "rb") as f:
        if file_size <= LARGE_FILE_THRESHOLD:
            while chunk := f.read(65536):
                sha256.update(chunk)
        else:
            # Sample head + tail for large files
            sha256.update(f.read(1024 * 1024))
            f.seek(-1024 * 1024, 2)
            sha256.update(f.read(1024 * 1024))

    return sha256.hexdigest()


def generate_content_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_image_hash(image_path: str) -> str:
    with Image.open(image_path) as image:
        return str(imagehash.phash(image.convert("RGB")))


# =====================================================
# CONTENT EXTRACTION (per file kind)
# =====================================================
def extract_video_metadata(file_path: str) -> str:
    """
    Uses ffprobe (if available) to extract video metadata as text.
    Falls back to filename + size if ffprobe is not installed.
    """
    try:
        import subprocess
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                file_path,
            ],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            streams = data.get("streams", [])
            duration = fmt.get("duration", "unknown")
            size_mb = round(int(fmt.get("size", 0)) / (1024 * 1024), 2)
            tags = fmt.get("tags", {})
            title = tags.get("title", "")
            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            resolution = ""
            if video_streams:
                w = video_streams[0].get("width", "")
                h = video_streams[0].get("height", "")
                resolution = f"{w}x{h}"
            return (
                f"Video file. Title: {title}. Duration: {duration}s. "
                f"Resolution: {resolution}. Size: {size_mb}MB. "
                f"Tags: {json.dumps(tags)}"
            )
    except Exception as e:
        logger.warning(f"ffprobe extraction failed: {e}")

    # Fallback
    size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
    return f"Video file. Size: {size_mb}MB. Filename: {os.path.basename(file_path)}"


def extract_data_file_content(file_path: str) -> str:
    """
    For CSV / TSV / JSON / Excel — returns a text summary.
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in {".csv", ".tsv"}:
            import pandas as pd
            sep = "\t" if ext == ".tsv" else ","
            df = pd.read_csv(file_path, sep=sep, nrows=5)
            return (
                f"Tabular data file. Columns: {list(df.columns)}. "
                f"Shape: {df.shape}. Sample:\n{df.head(3).to_string()}"
            )
        elif ext == ".json":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read(3000)
            return f"JSON file. Content preview: {raw}"
        elif ext in {".xlsx", ".xls"}:
            import pandas as pd
            df = pd.read_excel(file_path, nrows=5)
            return (
                f"Excel spreadsheet. Columns: {list(df.columns)}. "
                f"Shape: {df.shape}. Sample:\n{df.head(3).to_string()}"
            )
    except Exception as e:
        logger.warning(f"Data extraction failed for {file_path}: {e}")
    return f"Data file: {os.path.basename(file_path)}"


def extract_audio_metadata(file_path: str) -> str:
    """
    Uses mutagen (if installed) to pull audio tags. Falls back gracefully.
    """
    try:
        from mutagen import File as MutaFile
        audio = MutaFile(file_path, easy=True)
        if audio:
            tags = dict(audio.tags or {})
            info = audio.info
            duration = getattr(info, "length", "unknown")
            return (
                f"Audio file. Tags: {tags}. Duration: {duration:.1f}s."
            )
    except Exception as e:
        logger.warning(f"Audio metadata extraction failed: {e}")
    return f"Audio file: {os.path.basename(file_path)}"


def extract_content(file_path: str, file_kind: str) -> str:
    """
    Unified content extractor. Routes by file kind.
    """
    try:
        if file_kind == "image":
            return analyze_image(
                file_path,
                "Extract all important text and describe the content of this image document."
            )
        elif file_kind == "video":
            return extract_video_metadata(file_path)
        elif file_kind == "audio":
            return extract_audio_metadata(file_path)
        elif file_kind == "data":
            return extract_data_file_content(file_path)
        else:
            # PDF, DOCX, TXT, code files
            return extract_text(file_path)
    except Exception as e:
        logger.error(f"Content extraction failed for {file_path}: {e}")
        return ""


# =====================================================
# CATEGORY DETECTION
# Combines file kind + keyword scan for accuracy
# =====================================================
# =====================================================
# CATEGORY DETECTION — FIXED
# Priority order matters: most specific → most general
# Images now go through content check first
# =====================================================

CATEGORY_RULES = [
    # (category_name, [keywords]) — ORDER DETERMINES PRIORITY
    ("Government_Documents", [
        "government of india", "election commission", "aadhaar",
        "unique identification authority", "income tax department",
        "permanent account number", "voter id", "identity card",
        "passport", "ministry", "gazette", "uidai",
    ]),
    ("Resume", [
        "resume", "curriculum vitae", " cv ", "career objective",
        "work experience", "internship", "references", "linkedin",
        "seeking a position", "professional summary",
    ]),
    ("Finance", [
        "bank", "invoice", "transaction", "payment", "receipt",
        "balance", "account statement", "passbook", "gst", "salary",
        "payslip", "ledger", "credit", "debit", "loan", "ifsc",
    ]),
    ("Education", [
        "course", "student", "university", "education", "college",
        "marksheet", "grades", "semester", "degree", "assignment",
        "exam", "school",
    ]),
    ("Legal", [
        "agreement", "contract", "hereby", "whereas",
        "terms and conditions", "jurisdiction", "clause", "arbitration",
    ]),
    ("Medical", [
        "patient", "diagnosis", "prescription", "hospital", "doctor",
        "medicine", "dosage", "lab", "clinical",
    ]),
]

# Only fall back to these if content has NO keyword matches
KIND_FALLBACK_MAP = {
    "video": "Media_Video",
    "audio": "Media_Audio",
    "image": "Media_Image",   # ← fallback only, not default
    "data":  "Data_Files",
    "code":  "Code",
}

def detect_category(content_text: str, file_kind: str) -> str:
    # Non-document, non-image kinds skip content check entirely
    if file_kind in {"video", "audio", "data", "code"}:
        return KIND_FALLBACK_MAP[file_kind]

    # Images AND documents both go through keyword detection
    text = content_text.lower()

    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in text:
                return category

    # Nothing matched — use kind-based fallback
    # Images with no readable content → Media_Image
    # Documents with no matched keywords → General
    return KIND_FALLBACK_MAP.get(file_kind, "General")


# =====================================================
# FILENAME HELPERS
# =====================================================
def clean_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_\- ]", "", name)
    name = name.replace(" ", "_")
    return name.strip("_")


def generate_unique_filename(folder: str, filename: str) -> str:
    base_name, extension = os.path.splitext(filename)
    unique_filename = filename
    counter = 1
    while os.path.exists(os.path.join(folder, unique_filename)):
        unique_filename = f"{base_name}_{counter}{extension}"
        counter += 1
    return unique_filename


# =====================================================
# AI NAMING — Robust structured prompt + fallback chain
# =====================================================
FALLBACK_NAMES = {
    "Government_Documents": "Government_Doc",
    "Finance":              "Finance_Doc",
    "Education":            "Education_File",
    "Resume":               "Resume",
    "Legal":                "Legal_Doc",
    "Medical":              "Medical_Record",
    "Media_Video":          "Video_File",
    "Media_Audio":          "Audio_File",
    "Media_Image":          "Image_File",
    "Data_Files":           "Data_File",
    "Code":                 "Code_File",
    "General":              "File",
}

def smart_name_from_ai(
    content_text: str,
    original_filename: str,
    category: str,
    file_kind: str,
) -> tuple[str, str]:
    """
    Ask AI for a filename. Returns (clean_name, raw_ai_response).
    Uses a strict JSON output format so parsing never fails.
    """
    kind_hint = {
        "video":    "This is a VIDEO file — name it based on topic/subject matter.",
        "audio":    "This is an AUDIO file — name it based on topic/artist/title if available.",
        "image":    "This is an IMAGE — name it based on what the image contains.",
        "data":     "This is a DATA FILE (CSV/JSON/Excel) — name it based on the dataset subject.",
        "code":     "This is a CODE FILE — name it based on what the code does.",
        "document": "This is a DOCUMENT — name it based on its main topic.",
    }.get(file_kind, "")

    prompt = f"""You are a file naming assistant. Your job is to generate a short, descriptive filename.

{kind_hint}
Category detected: {category}
Original filename: {original_filename}

Rules:
1. Max 4 words, no special characters, no spaces (use underscores)
2. Be specific — avoid generic words like "Document", "File", "Report"
3. Use the content below as the primary signal
4. Return ONLY valid JSON — no explanation, no markdown

Required output format (exactly this):
{{"filename": "Your_Smart_Name"}}

Content preview:
{content_text[:2000]}
"""

    raw_response = ask_groq(prompt)

    # Robust JSON parsing with multiple fallback strategies
    smart_filename = _parse_filename_from_response(raw_response)

    if not smart_filename:
        # Last resort: use category fallback
        smart_filename = FALLBACK_NAMES.get(category, "File")

    return (clean_filename(smart_filename), raw_response)


def _parse_filename_from_response(response: str) -> str:
    """
    Try 3 strategies to extract a filename from the AI response.
    """
    if not response:
        return ""

    # Strategy 1: Valid JSON with "filename" key
    try:
        # Strip markdown fences if present
        clean = re.sub(r"```[a-z]*", "", response).strip().strip("`")
        data = json.loads(clean)
        if isinstance(data, dict) and "filename" in data:
            return str(data["filename"]).strip()
    except Exception:
        pass

    # Strategy 2: Regex — find {"filename": "..."} anywhere in the text
    match = re.search(r'"filename"\s*:\s*"([^"]+)"', response)
    if match:
        return match.group(1).strip()

    # Strategy 3: Legacy format "Smart Filename: ..."
    for line in response.split("\n"):
        if "filename" in line.lower() and ":" in line:
            candidate = line.split(":", 1)[-1].strip().strip('"')
            if candidate:
                return candidate

    return ""


# =====================================================
# UPLOAD ROUTE
# =====================================================
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
        # Use a unique temp name so two simultaneous uploads never collide
        # and a crash never leaves a named file sitting in uploads root
    import uuid
    temp_filename = f"_tmp_{uuid.uuid4().hex}{os.path.splitext(file.filename)[1]}"
    temp_path = os.path.join(UPLOAD_DIR, temp_filename)  # ← was file.filename

    with open(temp_path, "wb") as f:
        f.write(await file.read())
    logger.info(f"Received: {file.filename}")

    file_kind = get_file_kind(file.filename)

    # ── 2. File hash (fast for large files) ──────────────────────────────────
    file_hash = generate_file_hash(temp_path)

    # ── 3. Perceptual hash for images ────────────────────────────────────────
    image_hash = None
    if file_kind == "image":
        try:
            image_hash = generate_image_hash(temp_path)
        except Exception as e:
            logger.error(f"Image hash error: {e}")

    # ── 4. Content extraction ─────────────────────────────────────────────────
    content_text = extract_content(temp_path, file_kind) or ""
    content_hash = generate_content_hash(content_text)

    # ── 5. Duplicate detection ────────────────────────────────────────────────
    existing_metadata = load_metadata()

    for item in existing_metadata:
        # Check 1: Exact same original filename
        if item.get("original_filename", "").lower() == file.filename.lower():
            os.remove(temp_path)
            return _duplicate_response("filename", item)

        # Check 2: Exact same file bytes (hash)
        if item.get("file_hash") == file_hash:
            os.remove(temp_path)
            return _duplicate_response("file bytes", item)

        # Check 3: Same extracted content (catches re-saved/re-exported docs)
        # Skip for very short content to avoid false positives on empty files
        if len(content_text) > 50 and item.get("content_hash") == content_hash:
            os.remove(temp_path)
            return _duplicate_response("content", item)

        # Check 4: Visually identical image (phash distance <= 8)
        if image_hash and item.get("image_hash"):
            try:
                dist = imagehash.hex_to_hash(image_hash) - imagehash.hex_to_hash(item["image_hash"])
                if dist <= 8:
                    os.remove(temp_path)
                    return _duplicate_response("visual similarity", item)
            except Exception:
                pass

    # ── 6. Category detection ─────────────────────────────────────────────────
    category = clean_filename(detect_category(content_text, file_kind))

    # ── 7. AI naming ──────────────────────────────────────────────────────────
    smart_filename, ai_response = smart_name_from_ai(
        content_text, file.filename, category, file_kind
    )

    # ── 8. Create category folder + move file ─────────────────────────────────
    category_folder = os.path.join(UPLOAD_DIR, category)
    os.makedirs(category_folder, exist_ok=True)

    file_extension = os.path.splitext(file.filename)[1].lower()
    new_filename = generate_unique_filename(
        category_folder,
        f"{smart_filename}{file_extension}"
    )
    new_file_path = os.path.join(category_folder, new_filename)
    os.rename(temp_path, new_file_path)

    logger.info(f"Stored: {file.filename} → {category}/{new_filename}")

    # ── 9. Save metadata ──────────────────────────────────────────────────────
    metadata = {
        "original_filename": file.filename,
        "new_filename": new_filename,
        "category": category,
        "file_kind": file_kind,
        "summary": ai_response,
        "file_hash": file_hash,
        "content_hash": content_hash,
        "image_hash": image_hash,
        "file_size": os.path.getsize(new_file_path),
    }
    save_metadata(metadata)

    return {
        "original_filename": file.filename,
        "new_filename": new_filename,
        "category": category,
        "file_kind": file_kind,
        "duplicate_detected": False,
        "ai_analysis": ai_response,
    }


def _duplicate_response(reason: str, item: dict) -> dict:
    return {
        "message": f"Duplicate detected ({reason})",
        "existing_file": item.get("new_filename", item.get("original_filename")),
        "category": item.get("category"),
        "duplicate_detected": True,
    }


# =====================================================
# SEARCH ROUTE
# =====================================================
@router.get("/search")
def search_files(query: str = Query(...)):
    results = search_metadata(query)
    return {"query": query, "results": results}


# =====================================================
# STATS ROUTE
# =====================================================
@router.get("/stats")
def get_stats():
    metadata = load_metadata()
    category_counter = Counter()
    filetype_counter = Counter()
    kind_counter = Counter()
    total_size = 0

    for item in metadata:
        category_counter[item.get("category", "Unknown")] += 1
        ext = os.path.splitext(item.get("new_filename", ""))[1].lower()
        filetype_counter[ext] += 1
        kind_counter[item.get("file_kind", "other")] += 1
        total_size += item.get("file_size", 0)

    return {
        "total_files": len(metadata),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "categories": dict(category_counter),
        "file_types": dict(filetype_counter),
        "file_kinds": dict(kind_counter),
    }


# =====================================================
# FILE SERVE ROUTE
# =====================================================
@router.get("/file/{category}/{filename}")
def open_file(category: str, filename: str):
    file_path = os.path.join(UPLOAD_DIR, category, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found", "path": f"{category}/{filename}"}

@router.get("/explorer")
def file_explorer():

    metadata = load_metadata()

    grouped = {}

    for item in metadata:

        category = item.get(
            "category",
            "General"
        )

        if category not in grouped:

            grouped[category] = []

        grouped[category].append(item)

    return grouped