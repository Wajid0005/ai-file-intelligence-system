from fastapi import FastAPI, Request

from fastapi.staticfiles import StaticFiles

from fastapi.templating import Jinja2Templates

from app.routes.upload import (
    router as upload_router
)

from app.services.gemini_service import (
    ask_groq
)

app = FastAPI()


# =====================================================
# STATIC FILES
# =====================================================
app.mount(
    "/static",
    StaticFiles(
        directory="frontend/static"
    ),
    name="static"
)


# =====================================================
# HTML TEMPLATES
# =====================================================
templates = Jinja2Templates(
    directory="frontend/templates"
)


# =====================================================
# ROUTERS
# =====================================================
app.include_router(
    upload_router
)


# =====================================================
# HOME PAGE
# =====================================================
@app.get("/")
def home(
    request: Request
):

    return templates.TemplateResponse(
        request = request,
        name = "index.html"
    )


# =====================================================
# AI TEST ROUTE
# =====================================================
@app.get("/ai-test")
def test_ai():

    response = ask_groq(
        """
        Say hello like an AI assistant.
        """
    )

    return {
        "response": response
    }

app.mount(
    "/metadata",
    StaticFiles(directory="metadata"),
    name="metadata"
)