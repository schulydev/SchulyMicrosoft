class SignInState:
    """A password sign-in's states. Transient ones mean "the worker is busy"; everything else is a place the caller can act on."""

    WORKING, STARTING_PUSH, STARTING_OTP, VERIFYING = "working", "starting_push", "starting_otp", "verifying"
    MFA_REQUIRED, PUSH_PENDING, OTP_REQUIRED = "mfa_required", "push_pending", "otp_required"
    DENIED, TIMED_OUT, COMPLETE, ERROR = "denied", "timed_out", "complete", "error"
    TRANSIENT = {WORKING, STARTING_PUSH, STARTING_OTP, VERIFYING}
    CHOOSABLE = {MFA_REQUIRED, DENIED, TIMED_OUT}  # states where /method picks a (new) method
    PASSWORD_REFUSED = frozenset({"invalid_credentials", "password_expired", "no_password"})  # error codes for "Microsoft did not take the password"
