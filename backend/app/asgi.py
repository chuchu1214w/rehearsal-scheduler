"""uvicorn 入口:uvicorn app.asgi:app --app-dir backend"""

from .main import create_app

app = create_app()
