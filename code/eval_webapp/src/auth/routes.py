"""Authentication routes for login and logout."""

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from eval_v2.config import TEMPLATES_DIR, COOKIE_NAME
from eval_v2.auth.manager import manager, get_user, verify_password

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/login")
async def login_page(request: Request):
    """Render the login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login form submission."""
    user = get_user(username.lower().strip())

    if not user or not verify_password(password, user["password"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    # Create access token
    access_token = manager.create_access_token(data={"sub": user["username"]})

    # Redirect to overview with cookie set
    response = RedirectResponse(url="/overview", status_code=302)
    manager.set_cookie(response, access_token)

    return response


@router.get("/logout")
async def logout():
    """Handle logout - clear the auth cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
