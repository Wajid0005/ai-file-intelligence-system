from groq import Groq
from app.config.settings import GROQ_API_KEY
import base64
import mimetypes

client = Groq(api_key=GROQ_API_KEY)


def ask_groq(prompt):
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content

def analyze_image(image_path, prompt):

    mime_type, _ = mimetypes.guess_type(image_path)

    with open(image_path, "rb") as image_file:

        image_data = image_file.read()

        base64_image = base64.b64encode(
            image_data
        ).decode("utf-8")

    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{mime_type};base64,"
                                f"{base64_image}"
                            )
                        }
                    }
                ]
            }
        ]
    )

    return completion.choices[0].message.content