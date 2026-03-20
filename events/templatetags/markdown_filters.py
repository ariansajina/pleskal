import markdown
import nh3
from django import template
from django.utils.safestring import mark_safe

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
    html = markdown.markdown(value, extensions=["fenced_code"])
    clean_html = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
    )
    return mark_safe(clean_html)  # noqa: S308
