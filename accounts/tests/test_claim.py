from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from accounts.models import ClaimCode, generate_claim_code

from .factories import UserFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear cache before each test to prevent rate limit interference."""
    cache.clear()


@pytest.mark.django_db
class TestClaimCodeModel:
    def test_generate_claim_code_length(self):
        code = generate_claim_code()
        assert len(code) == 8

    def test_generate_claim_code_no_ambiguous_chars(self):
        for _ in range(100):
            code = generate_claim_code()
            for c in "O0I1L":
                assert c not in code

    def test_is_valid_fresh_code(self):
        code = ClaimCode.objects.create(
            code="ABCD1234",
            expires_at=timezone.now() + timedelta(days=7),
        )
        assert code.is_valid is True
        assert code.is_claimed is False
        assert code.is_expired is False

    def test_is_expired(self):
        code = ClaimCode.objects.create(
            code="EXPD1234",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        assert code.is_expired is True
        assert code.is_valid is False

    def test_is_claimed(self):
        user = UserFactory.create()
        code = ClaimCode.objects.create(
            code="CLMD1234",
            expires_at=timezone.now() + timedelta(days=7),
            claimed_by=user,
            claimed_at=timezone.now(),
        )
        assert code.is_claimed is True
        assert code.is_valid is False

    def test_is_claimed_survives_user_deletion(self):
        user = UserFactory.create()
        code = ClaimCode.objects.create(
            code="DELD1234",
            expires_at=timezone.now() + timedelta(days=7),
            claimed_by=user,
            claimed_at=timezone.now(),
        )
        user.delete()
        code.refresh_from_db()
        assert code.is_claimed is True
        assert code.is_valid is False

    def test_str_returns_code(self):
        code = ClaimCode.objects.create(
            code="STRG1234",
            expires_at=timezone.now() + timedelta(days=7),
        )
        assert str(code) == "STRG1234"


@pytest.mark.django_db
class TestGenerateClaimCodesCommand:
    def test_generates_codes(self):
        out = StringIO()
        call_command(
            "generate_claim_codes",
            count=5,
            expires="2027-06-01",
            stdout=out,
        )
        lines = [line for line in out.getvalue().strip().split("\n") if line]
        assert len(lines) == 5
        assert ClaimCode.objects.count() == 5

    def test_codes_are_unique(self):
        out = StringIO()
        call_command(
            "generate_claim_codes",
            count=20,
            expires="2027-06-01",
            stdout=out,
        )
        codes = [line for line in out.getvalue().strip().split("\n") if line]
        assert len(set(codes)) == 20

    def test_invalid_count_raises(self):
        with pytest.raises(Exception, match="Count must be between"):
            call_command("generate_claim_codes", count=0, expires="2027-06-01")

    def test_past_expiry_raises(self):
        with pytest.raises(Exception, match="future"):
            call_command("generate_claim_codes", count=1, expires="2020-01-01")


@pytest.mark.django_db
class TestClaimCodeView:
    def test_get_claim_page(self):
        client = Client()
        response = client.get("/claim/")
        assert response.status_code == 200

    def test_valid_code_redirects_to_register(self):
        ClaimCode.objects.create(
            code="TESTCODE",
            expires_at=timezone.now() + timedelta(days=7),
        )
        client = Client()
        response = client.post("/claim/", {"code": "TESTCODE"})
        assert response.status_code == 302
        assert "/claim/register/" in response.url

    def test_case_insensitive_code(self):
        ClaimCode.objects.create(
            code="TESTCODE",
            expires_at=timezone.now() + timedelta(days=7),
        )
        client = Client()
        response = client.post("/claim/", {"code": "testcode"})
        assert response.status_code == 302

    def test_invalid_code_shows_error(self):
        client = Client()
        response = client.post("/claim/", {"code": "BADCODE1"})
        assert response.status_code == 200
        assert b"Invalid code" in response.content

    def test_expired_code_shows_error(self):
        ClaimCode.objects.create(
            code="EXPDCODE",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        client = Client()
        response = client.post("/claim/", {"code": "EXPDCODE"})
        assert response.status_code == 200
        assert b"expired" in response.content

    def test_claimed_code_shows_error(self):
        user = UserFactory.create()
        ClaimCode.objects.create(
            code="USEDCODE",
            expires_at=timezone.now() + timedelta(days=7),
            claimed_by=user,
            claimed_at=timezone.now(),
        )
        client = Client()
        response = client.post("/claim/", {"code": "USEDCODE"})
        assert response.status_code == 200
        assert b"already been used" in response.content


@pytest.mark.django_db
class TestClaimRegisterView:
    def _create_valid_session(self, client):
        """Create a valid claim code and store it in session."""
        ClaimCode.objects.create(
            code="REGCODE1",
            expires_at=timezone.now() + timedelta(days=7),
        )
        client.post("/claim/", {"code": "REGCODE1"})

    def test_redirects_without_session(self):
        client = Client()
        response = client.get("/claim/register/")
        assert response.status_code == 302
        assert "/claim/" in response.url

    def test_get_register_page_with_valid_session(self):
        client = Client()
        self._create_valid_session(client)
        response = client.get("/claim/register/")
        assert response.status_code == 200

    def test_successful_registration(self):
        client = Client()
        self._create_valid_session(client)
        response = client.post(
            "/claim/register/",
            {
                "email": "newuser@example.com",
                "display_name": "New User",
                "password1": "CorrectHorse99!",
                "password2": "CorrectHorse99!",
            },
        )
        # Redirects to login (email verification required before logging in)
        assert response.status_code == 302
        assert "/accounts/login/" in response.url
        # User created
        user = User.objects.get(email="newuser@example.com")
        assert user.display_name == "New User"
        # Code marked as claimed
        code = ClaimCode.objects.get(code="REGCODE1")
        assert code.is_claimed is True
        assert code.claimed_by == user

    def test_user_must_verify_email_before_login(self):
        client = Client()
        self._create_valid_session(client)
        client.post(
            "/claim/register/",
            {
                "email": "logged@example.com",
                "display_name": "Logged In",
                "password1": "CorrectHorse99!",
                "password2": "CorrectHorse99!",
            },
        )
        # Not logged in yet — must verify email first
        response = client.get("/accounts/profile/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_password_mismatch_shows_error(self):
        client = Client()
        self._create_valid_session(client)
        response = client.post(
            "/claim/register/",
            {
                "email": "mismatch@example.com",
                "display_name": "Mismatch",
                "password1": "CorrectHorse99!",
                "password2": "DifferentHorse99!",
            },
        )
        assert response.status_code == 200
        assert b"match" in response.content

    def test_duplicate_email_shows_error(self):
        UserFactory.create(email="taken@example.com")
        client = Client()
        self._create_valid_session(client)
        response = client.post(
            "/claim/register/",
            {
                "email": "taken@example.com",
                "display_name": "Dupe Email",
                "password1": "CorrectHorse99!",
                "password2": "CorrectHorse99!",
            },
        )
        assert response.status_code == 200
        assert b"already in use" in response.content

    def test_race_condition_claimed_during_registration(self):
        """If code gets claimed between session validation and form submit."""
        code = ClaimCode.objects.create(
            code="RACECODE",
            expires_at=timezone.now() + timedelta(days=7),
        )
        client = Client()
        client.post("/claim/", {"code": "RACECODE"})

        # Simulate race: claim the code before form submission
        other_user = UserFactory.create()
        code.claimed_by = other_user
        code.claimed_at = timezone.now()
        code.save()

        response = client.post(
            "/claim/register/",
            {
                "email": "racer@example.com",
                "display_name": "Racer",
                "password1": "CorrectHorse99!",
                "password2": "CorrectHorse99!",
            },
        )
        assert response.status_code == 302
        assert "/claim/" in response.url
        assert not User.objects.filter(display_name="Racer").exists()


@pytest.mark.django_db
class TestClaimCodeAdmin:
    def test_admin_can_access_claimcode_list(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(superuser)
        response = client.get("/admin/accounts/claimcode/")
        assert response.status_code == 200

    def test_admin_can_access_generate_view(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(superuser)
        response = client.get("/admin/accounts/claimcode/generate/")
        assert response.status_code == 200

    def test_admin_can_generate_codes(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(superuser)
        response = client.post(
            "/admin/accounts/claimcode/generate/",
            {"count": 5, "expires_at": "2027-12-31 23:59:59"},
            follow=True,
        )
        assert response.status_code == 200
        assert ClaimCode.objects.count() == 5
