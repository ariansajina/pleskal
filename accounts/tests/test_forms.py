import pytest

from accounts.forms import ProfileForm

from .factories import UserFactory


@pytest.mark.django_db
class TestProfileForm:
    def test_email_not_required(self):
        user = UserFactory.create()
        form = ProfileForm({}, instance=user)
        assert not form.fields["email"].required

    def test_clean_email_allows_own_email(self):
        user = UserFactory.create(email="test@example.com")
        form = ProfileForm({"email": "test@example.com"}, instance=user)
        assert form.is_valid()

    def test_clean_email_rejects_taken_email(self):
        UserFactory.create(email="taken@example.com")
        user = UserFactory.create(email="myemail@example.com")
        form = ProfileForm({"email": "taken@example.com"}, instance=user)
        assert not form.is_valid()
        assert "email" in form.errors

    def test_clean_email_allows_empty(self):
        user = UserFactory.create(email="test@example.com")
        form = ProfileForm({"email": ""}, instance=user)
        assert form.is_valid()

    def test_clean_email_case_insensitive_own_email(self):
        user = UserFactory.create(email="test@example.com")
        form = ProfileForm({"email": "Test@Example.com"}, instance=user)
        assert form.is_valid()

    def test_clean_email_rejects_case_insensitive_taken_email(self):
        UserFactory.create(email="taken@example.com")
        user = UserFactory.create(email="myemail@example.com")
        form = ProfileForm({"email": "Taken@Example.com"}, instance=user)
        assert not form.is_valid()

    def test_clean_email_rejects_address_pending_for_another_user(self):
        """Two users can't both be mid-change to the same target address —
        the loser would end up with a permanently unverified, orphaned row."""
        from allauth.account.models import EmailAddress

        other_user = UserFactory.create(email="other@example.com")
        EmailAddress.objects.create(
            user=other_user, email="wanted@example.com", primary=False, verified=False
        )
        user = UserFactory.create(email="myemail@example.com")
        form = ProfileForm({"email": "wanted@example.com"}, instance=user)
        assert not form.is_valid()
        assert "email" in form.errors

    def test_clean_email_allows_own_pending_address_resubmission(self):
        """Re-submitting the same pending address you already started a
        change to (e.g. re-clicking save) isn't a collision with yourself."""
        from allauth.account.models import EmailAddress

        user = UserFactory.create(email="old@example.com")
        EmailAddress.objects.create(
            user=user, email="pending@example.com", primary=False, verified=False
        )
        form = ProfileForm({"email": "pending@example.com"}, instance=user)
        assert form.is_valid()
