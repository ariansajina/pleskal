"""Tests for the /health/ and /health/db/ endpoints."""

from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse


def test_health_is_shallow(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
class TestHealthDb:
    def test_ok_when_database_responds(self, client):
        response = client.get(reverse("health_db"))

        assert response.status_code == 200
        assert response.content == b"ok"
        assert "no-cache" in response["Cache-Control"]

    def test_503_when_database_is_down(self, client):
        with patch(
            "config.urls.connection.cursor",
            side_effect=OperationalError("connection refused"),
        ):
            response = client.get(reverse("health_db"))

        assert response.status_code == 503
