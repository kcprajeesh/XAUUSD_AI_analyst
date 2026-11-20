import uvicorn

from app.main import app, settings

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, loop="asyncio", http="h11")
