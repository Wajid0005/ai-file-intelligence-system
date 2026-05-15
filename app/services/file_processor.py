from PyPDF2 import PdfReader
import pytesseract
from PIL import Image

def extract_text(file_path):
    if file_path.endswith(".txt"):

        with open(file_path,"r", encoding="utf-8") as f:
            return f.read()

    elif file_path.endswith(".pdf"):
        text = ""
        reader = PdfReader(file_path)

    elif file_path.endswith((".png", ".jpg", ".jpeg")):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text

        for page in reader.pages:
            text += page.extract_text()
        return text
    return "Unsupported File type"