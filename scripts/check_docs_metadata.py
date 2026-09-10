"""Check rendered documentation URLs before publishing to GitHub Pages."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path

LANGUAGES = ("en", "zh-CN", "fr", "ru", "es", "ja")


class Metadata(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.lang = ""
        self.canonicals: list[str] = []
        self.social: dict[str, str] = {}
        self.alternates: dict[str, str] = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))
        if tag == "link" and attrs.get("rel") == "alternate":
            self.alternates[attrs.get("hreflang", "")] = attrs.get("href", "")
        if tag == "meta" and attrs.get("property") in ("og:url", "twitter:url"):
            self.social[attrs["property"]] = attrs.get("content", "")


def check_page(html: str, relative_path: str, site_url: str) -> list[str]:
    metadata = Metadata(html)
    errors = []
    is_entry = relative_path == "index.html"
    language = "en" if is_entry else relative_path.split("/")[0]
    path = "en/" if is_entry else relative_path.removesuffix("index.html")
    expected = f"{site_url.rstrip('/')}/{path}"
    if metadata.canonicals != [expected]:
        errors.append(f"canonical must be {expected}; got {metadata.canonicals}")
    if metadata.lang != language:
        errors.append(f"html lang must be {language}; got {metadata.lang}")
    if is_entry:
        for locale in (*LANGUAGES, "x-default"):
            target = "en" if locale == "x-default" else locale
            if metadata.alternates.get(locale) != f"{site_url.rstrip('/')}/{target}/":
                errors.append(f"incorrect alternate URL for {locale}")
    else:
        for name in ("og:url", "twitter:url"):
            if metadata.social.get(name) != expected:
                errors.append(f"{name} must be {expected}; got {metadata.social.get(name)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir", type=Path)
    parser.add_argument(
        "--site-url", required=True, help="published URL including the project path"
    )
    args = parser.parse_args()
    pages = [args.build_dir / "index.html"]
    for locale in LANGUAGES:
        if not (args.build_dir / locale / "index.html").is_file():
            parser.error(f"missing built {locale} homepage")
        pages.extend(sorted((args.build_dir / locale).rglob("*.html")))
    failed = 0
    for page in pages:
        relative = page.relative_to(args.build_dir).as_posix()
        if not page.is_file():
            parser.error(f"missing built page: {relative}")
        for error in check_page(page.read_text(encoding="utf-8"), relative, args.site_url):
            print(f"{relative}: {error}")
            failed += 1
    print(f"Checked metadata for {len(pages)} pages: {failed} errors")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
