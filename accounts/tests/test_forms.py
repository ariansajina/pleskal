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
