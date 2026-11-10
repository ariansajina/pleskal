from allauth.account.adapter import DefaultAccountAdapter


class ClosedSignupAccountAdapter(DefaultAccountAdapter):
    """allauth adapter that never allows allauth's own signup.

    Registration is invite-only through the claim-code flow
    (accounts.views.ClaimRegisterView), which creates users directly. allauth
    is used only to verify email addresses, so its signup must stay closed
    even if its views are ever routed again.
    """

    def is_open_for_signup(self, request):
        return False
