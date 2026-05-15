from fastapi import FastAPI
from app.routes.upload import router as upload_router
from app.services.gemini_service import ask_groq
app = FastAPI()

app.include_router(upload_router)
@app.get("/")
def home():
    return {"message": "AI File Intelligence System Running"}

@app.get("/ai")
def test_ai():
    response = ask_groq("Say Hello like an AI assistant, Can you print the table of 29")

    return {"response": response}