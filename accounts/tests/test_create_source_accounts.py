"""Tests for the create_source_accounts management command."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

User = get_user_model()


def _write_sources(path, sources):
    path.write_text(json.dumps(sources), encoding="utf-8")


SAMPLE_SOURCES = [
    {
        "external_source": "testsource",
        "display_name": "Test Source",
        "email": "system.testsource@pleskal.internal",
        "website": "https://testsource.example.com",
    }
]


@pytest.mark.django_db
class TestCreateSourceAccounts:
    def _run(self, sources_file):
        """Monkeypatch SOURCES_FILE and run the command."""
        import accounts.management.commands.create_source_accounts as cmd_module

        original = cmd_module.SOURCES_FILE
        try:
            cmd_module.SOURCES_FILE = sources_file
            call_command("create_source_accounts")
        finally:
            cmd_module.SOURCES_FILE = original

    def test_creates_user_from_sources_file(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)
        assert User.objects.filter(email="system.testsource@pleskal.internal").exists()

    def test_created_user_has_correct_fields(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)
        user = User.objects.get(email="system.testsource@pleskal.internal")
        assert user.display_name == "Test Source"
        assert user.display_name_slug == "testsource"
        assert user.website == "https://testsource.example.com"
        assert user.is_system_account is True
        assert user.is_active is True

    def test_created_user_has_unusable_password(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)
        user = User.objects.get(email="system.testsource@pleskal.internal")
        assert not user.has_usable_password()

    def test_idempotent_second_run_does_not_duplicate(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)
        self._run(f)
        assert User.objects.filter(email="system.testsource@pleskal.internal").count() == 1

    def test_second_run_updates_display_name(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)

        updated = [{**SAMPLE_SOURCES[0], "display_name": "Updated Name"}]
        _write_sources(f, updated)
        self._run(f)

        user = User.objects.get(email="system.testsource@pleskal.internal")
        assert user.display_name == "Updated Name"

    def test_second_run_updates_website(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)

        updated = [{**SAMPLE_SOURCES[0], "website": "https://new.example.com"}]
        _write_sources(f, updated)
        self._run(f)

        user = User.objects.get(email="system.testsource@pleskal.internal")
        assert user.website == "https://new.example.com"

    def test_missing_file_raises(self, tmp_path):
        import accounts.management.commands.create_source_accounts as cmd_module

        original = cmd_module.SOURCES_FILE
        try:
            cmd_module.SOURCES_FILE = tmp_path / "nonexistent.json"
            with pytest.raises(CommandError, match="Sources file not found"):
                call_command("create_source_accounts")
        finally:
            cmd_module.SOURCES_FILE = original

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "sources.json"
        f.write_text("not valid json", encoding="utf-8")

        import accounts.management.commands.create_source_accounts as cmd_module

        original = cmd_module.SOURCES_FILE
        try:
            cmd_module.SOURCES_FILE = f
            with pytest.raises(CommandError, match="Invalid JSON"):
                call_command("create_source_accounts")
        finally:
            cmd_module.SOURCES_FILE = original

    def test_bio_is_empty(self, tmp_path):
        f = tmp_path / "sources.json"
        _write_sources(f, SAMPLE_SOURCES)
        self._run(f)
        user = User.objects.get(email="system.testsource@pleskal.internal")
        assert user.bio == ""

    def test_multiple_sources_all_created(self, tmp_path):
        sources = [
            {
                "external_source": "source1",
                "display_name": "Source One",
                "email": "system.source1@pleskal.internal",
                "website": "https://source1.example.com",
            },
            {
                "external_source": "source2",
                "display_name": "Source Two",
                "email": "system.source2@pleskal.internal",
                "website": "https://source2.example.com",
            },
        ]
        f = tmp_path / "sources.json"
        _write_sources(f, sources)
        self._run(f)
        assert User.objects.filter(is_system_account=True).count() == 2
