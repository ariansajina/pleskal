from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from accounts.models import ClaimCode

from .factories import UserFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


@pytest.fixture()
def user():
    return UserFactory.create()


@pytest.fixture()
def logged_in_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestMyInvitesViewGet:
    def test_requires_login(self):
        client = Client()
        resp = client.get("/accounts/invites/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    def test_empty_page(self, logged_in_client):
        resp = logged_in_client.get("/accounts/invites/")
        assert resp.status_code == 200
        assert resp.context["can_generate"] is True
        assert list(resp.context["codes"]) == []

    def test_shows_own_codes(self, logged_in_client, user):
        code = ClaimCode.objects.create(
            code="AAAA1111",
            expires_at=timezone.now() + timedelta(days=7),
            created_by=user,
        )
        resp = logged_in_client.get("/accounts/invites/")
        assert code.code in resp.content.decode()

    def test_does_not_show_other_users_codes(self, logged_in_client):
        other_user = UserFactory.create()
        ClaimCode.objects.create(
            code="BBBB2222",
            expires_at=timezone.now() + timedelta(days=7),
            created_by=other_user,
        )
        resp = logged_in_client.get("/accounts/invites/")
        assert "BBBB2222" not in resp.content.decode()

    def test_filter_active(self, logged_in_client, user):
        # Active code
        ClaimCode.objects.create(
            code="ACTV1234",
            expires_at=timezone.now() + timedelta(days=7),
            created_by=user,
        )
        # Expired code
        ClaimCode.objects.create(
            code="EXPD1234",
            expires_at=timezone.now() - timedelta(hours=1),
            created_by=user,
        )
        resp = logged_in_client.get("/accounts/invites/?filter=active")
        content = resp.content.decode()
        assert "ACTV1234" in content
        assert "EXPD1234" not in content

    def test_filter_claimed(self, logged_in_client, user):
        other = UserFactory.create()
        ClaimCode.objects.create(
            code="CLMD1234",
            expires_at=timezone.now() + timedelta(days=7),
            created_by=user,
            claimed_by=other,
            claimed_at=timezone.now(),
        )
        ClaimCode.objects.create(
            code="NCLM1234",
            expires_at=timezone.now() + timedelta(days=7),
            created_by=user,
        )
        resp = logged_in_client.get("/accounts/invites/?filter=claimed")
        content = resp.content.decode()
        assert "CLMD1234" in content
        assert "NCLM1234" not in content

    def test_htmx_returns_partial(self, logged_in_client):
        resp = logged_in_client.get(
            "/accounts/invites/", headers={"HX-Request": "true"}
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "<html" not in content.lower()


@pytest.fixture()
def _small_batch(settings):
    settings.CLAIM_CODES_PER_BATCH = 3
    settings.CLAIM_CODE_EXPIRY_DAYS = 7


@pytest.mark.django_db
@pytest.mark.usefixtures("_small_batch")
class TestMyInvitesViewPost:
    def test_generate_requires_login(self):
        client = Client()
        resp = client.post("/accounts/invites/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    def test_generate_creates_batch(self, logged_in_client, user):
        resp = logged_in_client.post("/accounts/invites/")
        assert resp.status_code == 302
        codes = ClaimCode.objects.filter(created_by=user)
        assert codes.count() == 3

    def test_generate_sets_correct_expiry(self, logged_in_client, user):
        before = timezone.now()
        logged_in_client.post("/accounts/invites/")
        after = timezone.now()
        code = ClaimCode.objects.filter(created_by=user).first()
        assert code.expires_at >= before + timedelta(days=7)
        assert code.expires_at <= after + timedelta(days=7)

    def test_generate_once_per_month_enforced(self, logged_in_client, user):
        logged_in_client.post("/accounts/invites/")
        assert ClaimCode.objects.filter(created_by=user).count() == 3
        # Second attempt in same month should be rejected
        logged_in_client.post("/accounts/invites/")
        assert ClaimCode.objects.filter(created_by=user).count() == 3

    def test_generate_resets_next_month(self, logged_in_client, user):
        # Generate codes, then backdate them to last month
        logged_in_client.post("/accounts/invites/")
        assert ClaimCode.objects.filter(created_by=user).count() == 3
        last_month = timezone.now() - timedelta(days=32)
        ClaimCode.objects.filter(created_by=user).update(created_at=last_month)

        # Should be able to generate again
        logged_in_client.post("/accounts/invites/")
        assert ClaimCode.objects.filter(created_by=user).count() == 6

    def test_can_generate_false_after_generation(self, logged_in_client):
        logged_in_client.post("/accounts/invites/")
        resp = logged_in_client.get("/accounts/invites/")
        assert resp.context["can_generate"] is False

    def test_generate_redirects_back(self, logged_in_client):
        resp = logged_in_client.post("/accounts/invites/")
        assert resp.status_code == 302
        assert resp.url == "/accounts/invites/"
