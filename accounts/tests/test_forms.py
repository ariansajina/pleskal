import pytest

from accounts.forms import ProfileForm

from .factories import UserFactory


@pytest.mark.django_db
class TestProfileForm:
    def test_email_not_required(self):
        user = UserFactory.create(username="formuser")
        form = ProfileForm({"username": "formuser"}, instance=user)
        assert not form.fields["email"].required

    def test_username_widget_has_class(self):
        user = UserFactory.create(username="formuser2")
        form = ProfileForm(instance=user)
        assert "form-input" in form.fields["username"].widget.attrs.get("class", "")

    def test_clean_username_allows_own_username(self):
        user = UserFactory.create(username="myuser")
        form = ProfileForm({"username": "myuser"}, instance=user)
        assert form.is_valid()

    def test_clean_username_rejects_taken_username(self):
        UserFactory.create(username="taken")
        user = UserFactory.create(username="myuser")
        form = ProfileForm({"username": "taken"}, instance=user)
        assert not form.is_valid()
        assert "username" in form.errors

    def test_clean_username_rejects_duplicate_on_create(self):
        UserFactory.create(username="existing")
        form = ProfileForm({"username": "existing"})
        assert not form.is_valid()
        assert "username" in form.errors
