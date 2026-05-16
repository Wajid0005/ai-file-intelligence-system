"""
file_processor.py
Extracts readable text from documents so the AI can name and categorise them.

Supported formats:
  Documents : .txt, .pdf, .docx, .md
  Images    : .png, .jpg, .jpeg, .webp  (OCR via Tesseract)
  Data      : .csv, .tsv, .json, .xlsx  (summary via pandas)
  Code      : .py, .js, .ts, .html, .css, etc. (raw text)

Adding a new format: add an elif branch in extract_text().
"""

import os
import sys
import platform
import traceback

# ── Optional-import helpers ──────────────────────────────────────────────────
# We import lazily so missing packages only break the formats that need them,
# not the entire service.

def _try_import(module: str):
    try:
        import importlib
        return importlib.import_module(module)
    except ImportError:
        return None


# ── Tesseract path (platform-aware) ─────────────────────────────────────────
def _configure_tesseract():
    """
    Set the Tesseract binary path based on the OS.
    Override with the TESSERACT_PATH environment variable if needed.
    """
    pytesseract = _try_import("pytesseract")
    if pytesseract is None:
        return None

    env_path = os.environ.get("TESSERACT_PATH")
    if env_path:
        pytesseract.pytesseract.tesseract_cmd = env_path
        return pytesseract

    if platform.system() == "Windows":
        default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    elif platform.system() == "Darwin":  # macOS (brew install tesseract)
        default = "/usr/local/bin/tesseract"
    else:                                # Linux
        default = "/usr/bin/tesseract"

    if os.path.exists(default):
        pytesseract.pytesseract.tesseract_cmd = default

    return pytesseract


_pytesseract = _configure_tesseract()


# ============================================================
# CORE EXTRACTION FUNCTION
# ============================================================
def extract_text(file_path: str) -> str:
    """
    Extract text content from a file.
    Returns a string (may be empty on failure — never raises).
    """
    if not os.path.exists(file_path):
        return ""

    ext = os.path.splitext(file_path)[1].lower()

    try:
        # ── Plain text / Markdown / Code ─────────────────────────────────────
        if ext in {".txt", ".md", ".py", ".js", ".ts", ".html",
                   ".css", ".java", ".cpp", ".c", ".rs", ".go"}:
            return _read_text_file(file_path)

        # ── PDF ───────────────────────────────────────────────────────────────
        elif ext == ".pdf":
            return _extract_pdf(file_path)

        # ── DOCX ──────────────────────────────────────────────────────────────
        elif ext in {".docx", ".doc"}:
            return _extract_docx(file_path)

        # ── Images (OCR) ──────────────────────────────────────────────────────
        elif ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
            return _extract_image_ocr(file_path)

        # ── CSV / TSV ─────────────────────────────────────────────────────────
        elif ext in {".csv", ".tsv"}:
            return _extract_csv(file_path)

        # ── Excel ─────────────────────────────────────────────────────────────
        elif ext in {".xlsx", ".xls"}:
            return _extract_excel(file_path)

        # ── JSON ──────────────────────────────────────────────────────────────
        elif ext == ".json":
            return _read_text_file(file_path, max_chars=3000)

        else:
            return f"Unsupported file type: {ext}"

    except Exception:
        # Log but never crash the upload pipeline
        traceback.print_exc()
        return ""


# ============================================================
# INDIVIDUAL EXTRACTORS
# ============================================================

def _read_text_file(file_path: str, max_chars: int = 10_000) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read(max_chars)


def _extract_pdf(file_path: str) -> str:
    """
    Uses pypdf (modern) with fallback to PyPDF2 (legacy).
    Falls back to Tesseract OCR for scanned/image-only PDFs.
    """
    text = ""

    # Try pypdf first (actively maintained)
    pypdf = _try_import("pypdf")
    if pypdf:
        try:
            reader = pypdf.PdfReader(file_path)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text += page_text
        except Exception:
            text = ""

    # Fallback to PyPDF2
    if not text.strip():
        PyPDF2 = _try_import("PyPDF2")
        if PyPDF2:
            try:
                reader = PyPDF2.PdfReader(file_path)
                for page in reader.pages:
                    page_text = page.extract_text() or ""
                    text += page_text
            except Exception:
                text = ""

    # If still empty, it's likely a scanned PDF — try OCR via pdf2image
    if not text.strip():
        text = _ocr_pdf(file_path)

    return text.strip()


def _ocr_pdf(file_path: str) -> str:
    """
    Converts PDF pages to images and runs Tesseract OCR.
    Requires: pdf2image + poppler + tesseract
    """
    if _pytesseract is None:
        return ""

    pdf2image = _try_import("pdf2image")
    if pdf2image is None:
        return ""

    try:
        pages = pdf2image.convert_from_path(file_path, dpi=200, first_page=1, last_page=3)
        text = ""
        for page_img in pages:
            text += _pytesseract.image_to_string(page_img)
        return text.strip()
    except Exception:
        traceback.print_exc()
        return ""


def _extract_docx(file_path: str) -> str:
    """
    Extracts text from Word documents using python-docx.
    """
    docx = _try_import("docx")
    if docx is None:
        return _read_text_file(file_path)  # weak fallback

    try:
        doc = docx.Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract table text
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        return "\n".join(paragraphs)
    except Exception:
        traceback.print_exc()
        return ""


def _extract_image_ocr(file_path: str) -> str:
    """
    Runs Tesseract OCR on an image file.
    """
    if _pytesseract is None:
        return ""

    PIL = _try_import("PIL.Image")
    if PIL is None:
        return ""

    try:
        from PIL import Image
        image = Image.open(file_path).convert("RGB")
        return _pytesseract.image_to_string(image).strip()
    except Exception:
        traceback.print_exc()
        return ""


def _extract_csv(file_path: str) -> str:
    """
    Returns a human-readable summary of a CSV/TSV file.
    """
    pd = _try_import("pandas")
    if pd is None:
        return _read_text_file(file_path, max_chars=2000)

    try:
        sep = "\t" if file_path.endswith(".tsv") else ","
        df = pd.read_csv(file_path, sep=sep, nrows=10)
        return (
            f"Tabular data file.\n"
            f"Columns ({len(df.columns)}): {list(df.columns)}\n"
            f"Rows in preview: {len(df)}\n"
            f"Sample data:\n{df.head(5).to_string(index=False)}"
        )
    except Exception:
        return _read_text_file(file_path, max_chars=2000)


def _extract_excel(file_path: str) -> str:
    """
    Returns a summary of the first sheet of an Excel file.
    """
    pd = _try_import("pandas")
    if pd is None:
        return "Excel file (pandas not installed)"

    try:
        xl = pd.ExcelFile(file_path)
        summaries = []
        for sheet in xl.sheet_names[:3]:  # Max 3 sheets
            df = xl.parse(sheet, nrows=5)
            summaries.append(
                f"Sheet '{sheet}': columns={list(df.columns)}, rows={df.shape[0]}\n"
                f"{df.head(3).to_string(index=False)}"
            )
        return "\n\n".join(summaries)
    except Exception:
        return "Excel file (extraction failed)"