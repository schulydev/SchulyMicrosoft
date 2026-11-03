from pydantic import BaseModel, Field


class BrowserStartResponse(BaseModel):
    authorize_url: str = Field(..., description="Open in a WebView; wait for the redirect to redirect_uri carrying ?code=.")
    redirect_uri: str = Field(..., description="The URL the code comes back on; the app watches for it and then closes the WebView.")
    code_verifier: str = Field(..., description="Opaque PKCE value; the caller holds it and sends it to /complete.")
