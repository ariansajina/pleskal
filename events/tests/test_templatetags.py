from events.templatetags.markdown_filters import render_markdown


class TestRenderMarkdown:
    def test_basic_markdown(self):
        result = render_markdown("**bold** and *italic*")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_headings(self):
        result = render_markdown("## Heading 2\n### Heading 3")
        assert "<h2>" in result
        assert "<h3>" in result

    def test_lists(self):
        result = render_markdown("- item 1\n- item 2")
        assert "<ul>" in result
        assert "<li>" in result

    def test_ordered_lists(self):
        result = render_markdown("1. first\n2. second")
        assert "<ol>" in result
        assert "<li>" in result

    def test_links(self):
        result = render_markdown("[link](https://example.com)")
        assert 'href="https://example.com"' in result
        assert ">link</a>" in result

    def test_code_blocks(self):
        result = render_markdown("```\ncode here\n```")
        assert "<code>" in result
        assert "<pre>" in result

    def test_blockquote(self):
        result = render_markdown("> quoted text")
        assert "<blockquote>" in result

    def test_empty_input(self):
        assert render_markdown("") == ""
        assert render_markdown(None) == ""

    # Security tests

    def test_script_tag_stripped(self):
        result = render_markdown("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "alert" not in result

    def test_javascript_href_stripped(self):
        result = render_markdown("[click](javascript:alert(1))")
        assert "javascript:" not in result

    def test_onclick_stripped(self):
        result = render_markdown('<a href="#" onclick="alert(1)">x</a>')
        assert "onclick" not in result

    def test_img_tag_stripped(self):
        result = render_markdown('<img src="x" onerror="alert(1)">')
        assert "<img" not in result

    def test_iframe_stripped(self):
        result = render_markdown('<iframe src="evil.com"></iframe>')
        assert "<iframe" not in result

    def test_style_tag_stripped(self):
        result = render_markdown("<style>body{display:none}</style>")
        assert "<style>" not in result

    def test_data_uri_stripped(self):
        result = render_markdown("[click](data:text/html,<script>alert(1)</script>)")
        assert "data:" not in result

    def test_mailto_allowed(self):
        result = render_markdown("[email](mailto:test@example.com)")
        assert "mailto:test@example.com" in result
