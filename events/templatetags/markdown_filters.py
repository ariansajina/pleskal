import html
import re

import markdown
import nh3
from django import template
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator

register = template.Library()

ALLOWED_TAGS = {
    "p",
    "a",
    "strong",
    "em",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "br",
    "blockquote",
    "code",
    "pre",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href"},
}

ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


@register.filter(name="render_markdown")
def render_markdown(value):
    """Render Markdown to sanitized HTML."""
    if not value:
        return ""
    rendered = markdown.markdown(value, extensions=["fenced_code"])
    clean_html = nh3.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
    )
    return mark_safe(clean_html)  # noqa: S308


@register.filter(name="plain_excerpt")
def plain_excerpt(value, length=160):
    """Markdown as one line of plain text, cut at ``length`` (for meta tags).

    The result is unescaped text, so autoescaping renders it correctly.
    """
    text = html.unescape(strip_tags(render_markdown(value)))
    return Truncator(re.sub(r"\s+", " ", text).strip()).chars(int(length))
