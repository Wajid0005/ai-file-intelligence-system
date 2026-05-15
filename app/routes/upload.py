from fastapi import APIRouter, UploadFile, File, Query
import os
import re
import hashlib

from PIL import Image
import imagehash

from app.utils.logger import logger
from app.services.file_processor import extract_text
from app.services.gemini_service import ask_groq, analyze_image
from app.services.metadata_manager import (
    save_metadata,
    load_metadata,
    search_metadata,
)

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =====================================================
# HASH HELPERS
# =====================================================
def generate_file_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(4096):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_content_hash(text: str) -> str:
    sha256 = hashlib.sha256()
    normalized = " ".join(text.lower().split())
    sha256.update(normalized.encode("utf-8"))
    return sha256.hexdigest()


def generate_image_hash(image_path: str) -> str:
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        return str(imagehash.phash(image))


# =====================================================
# TEXT HELPERS
# =====================================================
def clean_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_\- ]", "", name)
    name = name.replace(" ", "_")
    return name.strip("_")


def generate_unique_filename(folder: str, filename: str) -> str:
    base_name, extension = os.path.splitext(filename)
    counter = 1
    unique_filename = filename

    while os.path.exists(os.path.join(folder, unique_filename)):
        unique_filename = f"{base_name}_{counter}{extension}"
        counter += 1

    return unique_filename


def detect_category(text: str) -> str:
    text = text.lower()

    government_keywords = [
        "government of india",
        "election commission",
        "aadhaar",
        "unique identification authority",
        "income tax department",
        "permanent account number",
        "voter",
        "identity card",
        "passport",
    ]

    finance_keywords = ["bank", "invoice", "transaction", "payment"]
    education_keywords = ["course", "student", "university", "education"]
    resume_keywords = ["resume", "cv", "skills", "experience"]

    for word in government_keywords:
        if word in text:
            return "Government_Documents"

    for word in finance_keywords:
        if word in text:
            return "Finance"

    for word in education_keywords:
        if word in text:
            return "Education"

    for word in resume_keywords:
        if word in text:
            return "Resume"

    return "General"


def smart_name_from_ai(content_text: str, original_filename: str) -> tuple[str, str]:
    response = ask_groq(
        f"""
You are naming a document.

Rules:
- Use mostly document content
- Use filename only as a weak hint
- Keep it short, max 3 words
- No special characters
- Return only one line in this format:
Smart Filename: <name>

Original filename: {original_filename}
Document content:
{content_text[:3000]}
"""
    )

    smart_filename = "AI_File"
    for line in response.split("\n"):
        if "smart filename" in line.lower():
            smart_filename = line.split(":")[-1].strip()

    smart_filename = clean_filename(smart_filename)
    return (smart_filename if smart_filename else "AI_File", response)


def is_image_file(filename: str) -> bool:
    return filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))


# =====================================================
# UPLOAD ROUTE
# =====================================================
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # 1) Save uploaded file temporarily
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    logger.info(f"{file.filename} uploaded successfully")

    # 2) Generate raw file hash immediately
    file_hash = generate_file_hash(file_path)

    # 3) If image, generate perceptual hash too
    image_hash = None
    if is_image_file(file.filename):
        try:
            image_hash = generate_image_hash(file_path)
        except Exception as e:
            logger.error(f"Image hash error for {file.filename}: {e}")
            image_hash = None

    # 4) Extract text/content
    if is_image_file(file.filename):
        try:
            content_text = analyze_image(
                file_path,
                "Extract all important information from this image document."
            )
        except Exception as e:
            logger.error(f"Vision analysis failed for {file.filename}: {e}")
            content_text = ""
    else:
        try:
            content_text = extract_text(file_path)
        except Exception as e:
            logger.error(f"Text extraction failed for {file.filename}: {e}")
            content_text = ""

    content_text = content_text or ""
    content_hash = generate_content_hash(content_text)

    # 5) Duplicate check from metadata
    existing_metadata = load_metadata()

    for item in existing_metadata:
        # exact same original filename
        if item.get("original_filename", "").lower() == file.filename.lower():
            os.remove(file_path)
            return {
                "message": "Duplicate filename detected",
                "existing_file": item.get("new_filename", item.get("original_filename"))
            }

        # exact same file bytes
        if item.get("file_hash") == file_hash:
            os.remove(file_path)
            return {
                "message": "Duplicate file detected",
                "existing_file": item.get("new_filename", item.get("original_filename"))
            }

        # same extracted content
        if item.get("content_hash") == content_hash:
            os.remove(file_path)
            return {
                "message": "Duplicate content detected",
                "existing_file": item.get("new_filename", item.get("original_filename"))
            }

        # same visual image
        if image_hash and item.get("image_hash") == image_hash:
            os.remove(file_path)
            return {
                "message": "Duplicate image detected",
                "existing_file": item.get("new_filename", item.get("original_filename"))
            }

    # 6) Category detection
    category = clean_filename(detect_category(content_text))

    # 7) AI naming
    smart_filename, ai_response = smart_name_from_ai(
        content_text,
        file.filename
    )

    # Human-friendly fallback naming
    if smart_filename == "" or smart_filename.lower() == "ai_file":
        if category == "Government_Documents":
            smart_filename = "Government_ID"
        elif category == "Finance":
            smart_filename = "Finance_Document"
        elif category == "Education":
            smart_filename = "Education_File"
        elif category == "Resume":
            smart_filename = "Resume"
        else:
            smart_filename = "File"

    # 8) Create category folder
    category_folder = os.path.join(UPLOAD_DIR, category)
    os.makedirs(category_folder, exist_ok=True)

    # 9) Final file name
    file_extension = os.path.splitext(file.filename)[1]
    new_filename = generate_unique_filename(
        category_folder,
        f"{smart_filename}{file_extension}"
    )

    new_file_path = os.path.join(category_folder, new_filename)

    # 10) Move file
    os.rename(file_path, new_file_path)

    logger.info(f"{file.filename} renamed to {new_filename}")

    # 11) Save metadata
    metadata = {
        "original_filename": file.filename,
        "new_filename": new_filename,
        "category": category,
        "summary": ai_response,
        "file_hash": file_hash,
        "content_hash": content_hash,
        "image_hash": image_hash,
    }

    save_metadata(metadata)

    # 12) Return response
    return {
        "filename": file.filename,
        "new_filename": new_filename,
        "category": category,
        "duplicate_detected": False,
        "ai_analysis": ai_response,
    }


# =====================================================
# SEARCH ROUTE
# =====================================================
@router.get("/search")
def search_files(query: str = Query(...)):
    results = search_metadata(query)
    return {
        "query": query,
        "results": results
    }