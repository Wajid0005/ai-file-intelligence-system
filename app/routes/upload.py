from fastapi import APIRouter, UploadFile, File
import os
import re
import hashlib
from app.utils.logger import logger
from app.services.file_processor import extract_text
from app.services.gemini_service import ask_groq
from app.services.metadata_manager import (
    save_metadata,
    load_metadata
)
router = APIRouter()

UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)


def generate_file_hash(file_path):
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        while chunk := f.read(4096):
            sha256.update(chunk)

    return  sha256.hexdigest()

def clean_filename(name):

    name = re.sub(r'[^a-zA-Z0-9_\- ]', '', name)

    name = name.replace(" ", "_")

    return name

def generate_unique_filename(folder, filename):
    base_name, extension = os.path.splitext(filename)
    counter = 1

    unique_filename = filename
    while os.path.exists(
        os.path.join(folder, unique_filename)
    ):

        unique_filename = (
            f"{base_name}_{counter}{extension}"
        )
        counter +=1
    return unique_filename

def detect_category(text):

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
        "passport"
    ]

    finance_keywords = [
        "bank",
        "invoice",
        "transaction",
        "payment"
    ]

    education_keywords = [
        "course",
        "student",
        "university",
        "education"
    ]

    resume_keywords = [
        "resume",
        "cv",
        "skills",
        "experience"
    ]

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


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    # Save uploaded file
    file_path = os.path.join(
        UPLOAD_DIR,
        file.filename
    )

    with open(file_path, "wb") as f:

        content = await file.read()

        f.write(content)

    logger.info(
        f"{file.filename} uploaded successfully"
    )

    # OCR / Text Extraction
    text = extract_text(file_path)

    # Detect category using OCR text
    category = detect_category(text)

    category = clean_filename(category)

    # AI naming + summary
    ai_response = ask_groq(
        f"""
        Analyze this document.

        Return ONLY in this exact format:

        Smart Filename:
        Summary:

        Rules:
        - Smart filename should be short
        - Maximum 3 words
        - No special characters
        - Make meaningful names

        File Content:
        {text[:3000]}
        """
    )

    # Default filename
    smart_filename = "AI_File"

    # Extract filename from AI response
    for line in ai_response.split("\n"):

        if line.startswith("Smart Filename:"):

            smart_filename = line.replace(
                "Smart Filename:",
                ""
            ).strip()

    # Clean filename
    smart_filename = clean_filename(
        smart_filename
    )

    # Fallback names
    if smart_filename == "":

        if category == "Government_Documents":
            smart_filename = "Government_ID"

        elif category == "Finance":
            smart_filename = "Finance_Document"

        elif category == "Education":
            smart_filename = "Education_File"

        elif category == "Resume":
            smart_filename = "Resume"

        else:
            smart_filename = "AI_File"

    # Create category folder
    category_folder = os.path.join(
        UPLOAD_DIR,
        category
    )

    os.makedirs(
        category_folder,
        exist_ok=True
    )

    # File extension
    file_extension = os.path.splitext(
        file.filename
    )[1]

    # Final filename
    new_filename = generate_unique_filename(
        category_folder,
        f"{smart_filename}{file_extension}"
    )

    new_file_path = os.path.join(
        category_folder,
        new_filename
    )

    file_hash = generate_file_hash((file_path))

    existing_metadata = load_metadata()
    for item in existing_metadata:
        if item.get("file_hash") == file_hash:

            return{
                "message": "Duplicate file detected",
                "existing_file": item["new_filename"]
            }
    # Rename + move file
    os.rename(
        file_path,
        new_file_path
    )

    logger.info(
        f"{file.filename} renamed to {new_filename}"
    )

    # Save metadata
    metadata = {
        "original_filename": file.filename,
        "new_filename": new_filename,
        "category": category,
        "summary": ai_response,
        "file_hash": file_hash
    }

    save_metadata(metadata)

    return {
        "filename": file.filename,
        "new_filename": new_filename,
        "category": category,
        "ai_analysis": ai_response
    }
