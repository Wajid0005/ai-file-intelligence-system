"""
gemini_service.py  (still powered by Groq — name kept for import compatibility)

Improvements over original:
  - max_tokens on every call (prevents runaway costs / slow responses)
  - Retry logic with exponential back-off for transient API errors
  - Separate temperature per use-case (naming = deterministic, analysis = creative)
  - ask_groq returns "" on failure instead of raising (never crashes upload)
  - analyze_image validates mime type before sending
  - Model names in one place — easy to swap
"""

import time
import base64
import mimetypes
import traceback

from groq import Groq, APIError, APITimeoutError, RateLimitError
from app.config.settings import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

# ── Model config (change here only) ─────────────────────────────────────────
TEXT_MODEL   = "llama-3.1-8b-instant"       # Fast, cheap — good for naming
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

# ── Retry config ─────────────────────────────────────────────────────────────
MAX_RETRIES    = 3
RETRY_DELAY    = 2   # seconds (doubles each retry)


# ============================================================
# INTERNAL RETRY WRAPPER
# ============================================================
def _call_with_retry(fn, *args, **kwargs):
    """
    Calls fn(*args, **kwargs) up to MAX_RETRIES times.
    Retries on rate-limit and timeout errors. Returns None on final failure.
    """
    delay = RETRY_DELAY
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except RateLimitError as e:
            last_error = e
            print(f"[Groq] Rate limit hit (attempt {attempt}/{MAX_RETRIES}). "
                  f"Retrying in {delay}s…")
            time.sleep(delay)
            delay *= 2
        except APITimeoutError as e:
            last_error = e
            print(f"[Groq] Timeout (attempt {attempt}/{MAX_RETRIES}). "
                  f"Retrying in {delay}s…")
            time.sleep(delay)
            delay *= 2
        except APIError as e:
            # Non-retryable API error (bad request, auth, etc.)
            print(f"[Groq] API error: {e}")
            return None
        except Exception as e:
            print(f"[Groq] Unexpected error: {e}")
            traceback.print_exc()
            return None

    print(f"[Groq] All {MAX_RETRIES} retries exhausted. Last error: {last_error}")
    return None


# ============================================================
# TEXT COMPLETION
# ============================================================
def ask_groq(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
) -> str:
    """
    Send a text prompt to the Groq LLM.

    Args:
        prompt:      The full prompt string.
        max_tokens:  Hard cap on response length. Keep low for naming tasks.
        temperature: 0.0–0.2 for deterministic naming; higher for summaries.

    Returns:
        Model response string, or "" on any failure.
    """
    def _call():
        return client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

    response = _call_with_retry(_call)
    if response is None:
        return ""

    try:
        return response.choices[0].message.content or ""
    except (IndexError, AttributeError):
        return ""


# ============================================================
# VISION / IMAGE ANALYSIS
# ============================================================
def analyze_image(image_path: str, prompt: str) -> str:
    """
    Send an image + prompt to the Groq vision model.

    Args:
        image_path: Local path to the image file.
        prompt:     Instruction for the model (e.g. "Extract all text…").

    Returns:
        Model response string, or "" on any failure.
    """
    # Validate mime type before making the API call
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type not in SUPPORTED_IMAGE_MIMES:
        print(f"[Groq Vision] Unsupported mime type: {mime_type} for {image_path}")
        return ""

    try:
        with open(image_path, "rb") as f:
            base64_image = base64.b64encode(f.read()).decode("utf-8")
    except OSError as e:
        print(f"[Groq Vision] Could not read file {image_path}: {e}")
        return ""

    def _call():
        return client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
            max_tokens=512,
            temperature=0.2,
        )

    response = _call_with_retry(_call)
    if response is None:
        return ""

    try:
        return response.choices[0].message.content or ""
    except (IndexError, AttributeError):
        return ""