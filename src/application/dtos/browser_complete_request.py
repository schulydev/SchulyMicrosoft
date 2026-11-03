from pydantic import BaseModel


class BrowserCompleteRequest(BaseModel):
    code: str
    code_verifier: str
