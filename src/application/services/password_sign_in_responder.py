from src.application.abstractions.i_sign_in_job import ISignInJob
from src.application.dtos.password_sign_in_response import PasswordSignInResponse
from src.application.services.linked_identity_reader import LinkedIdentityReader
from src.domain.sign_in.sign_in_state import SignInState


class PasswordSignInResponder:
    """A sign-in job's current place as a response. Reads progress only; the password is not on the job."""

    def __init__(self, identities: LinkedIdentityReader):
        self._identities = identities

    async def respond(self, job: ISignInJob) -> PasswordSignInResponse:
        snap = job.snapshot()
        state = snap["state"]
        base = {"sign_in_id": job.id}
        if state == SignInState.COMPLETE:
            if job.account is None:
                job.account = await self._identities.read(snap["refresh_token"])
            return PasswordSignInResponse(**base, status="complete", refresh_token=snap["refresh_token"], session_cookies=snap.get("session_cookies") or None, account=job.account)
        if state == SignInState.ERROR:
            return PasswordSignInResponse(**base, status="error", code=snap["code"], message=snap["message"])
        if state == SignInState.PUSH_PENDING:
            return PasswordSignInResponse(**base, status="push_pending", number=snap["number"], expires_in=snap["expires_in"], methods=snap["methods"])
        if state == SignInState.OTP_REQUIRED:
            status = "otp_invalid" if snap.get("otp_invalid") else "otp_required"
            return PasswordSignInResponse(**base, status=status, attempts_left=snap["attempts_left"], methods=snap["methods"])
        if state in (SignInState.MFA_REQUIRED, SignInState.DENIED, SignInState.TIMED_OUT):
            if snap["notice"] == "otp_exhausted":
                return PasswordSignInResponse(**base, status="otp_invalid", attempts_left=0, methods=snap["methods"], message="Too many wrong codes; choose a method again.")
            return PasswordSignInResponse(**base, status=state, methods=snap["methods"])
        return PasswordSignInResponse(**base, status="working")
