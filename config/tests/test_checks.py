"""Tests for config.checks."""

from config.checks import check_media_domain


def test_no_warning_without_r2(settings):
    settings.AWS_STORAGE_BUCKET_NAME = None
    assert check_media_domain(None) == []


def test_warns_without_custom_domain(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "media"
    settings.AWS_S3_CUSTOM_DOMAIN = None
    assert [w.id for w in check_media_domain(None)] == ["pleskal.W001"]


def test_warns_for_r2_dev_domain(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "media"
    settings.AWS_S3_CUSTOM_DOMAIN = "pub-123.r2.dev"
    assert [w.id for w in check_media_domain(None)] == ["pleskal.W001"]


def test_custom_domain_passes(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "media"
    settings.AWS_S3_CUSTOM_DOMAIN = "media.pleskal.dk"
    assert check_media_domain(None) == []
