import uvicorn

from src.api.app import app

if __name__ == "__main__":
    # workers=1 on purpose: password sign-in jobs live in this process memory (see src/infrastructure/password_signin).
    # access_log=False on purpose: query strings carry search text, file paths and mail folders, and must not reach the logs.
    uvicorn.run(app, host="0.0.0.0", port=8010, workers=1, access_log=False)
