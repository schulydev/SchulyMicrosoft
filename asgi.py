import uvicorn

from src.app import app

if __name__ == "__main__":
    # workers=1 on purpose: password sign-in jobs live in this process memory (see src/password_signin.py).
    uvicorn.run(app, host="0.0.0.0", port=8010, workers=1)
