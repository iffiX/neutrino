"""Check that the guide's pages and the shot table name the same images.

Fails when a page references a screenshot the table does not name for that
page, or when the table names a screenshot its page does not reference. A
screenshot is referenced as ``/guide/<language>/<name>.webp`` and named in
``shots.json`` as ``<name>.png`` under its English page path, in ``page`` or
in ``pages``; a ``zh`` entry belongs to the page under ``zh-CN/``, and an
``os`` or ``console`` entry to both. An ``os`` or ``console`` entry's
``language_pages`` maps ``en`` or ``zh`` to pages that one language alone
shows the image on. Pages the table lists as pending are skipped.

Run from anywhere: ``python3 packaging/screenshots/check_shots.py``.
"""

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
SHOTS_FILE = HERE / "shots.json"
GUIDE_DIR = REPOSITORY / "docs" / "guide"
CHINESE_PREFIX = "zh-CN/"
SKIPPED_DIRS = {"node_modules", ".vitepress", "public"}
SKIPPED_PAGES = {"README.md"}
# An image the build copies from images/guide/: /guide/<dir>/<name>.<ext>.
IMAGE_REFERENCE = re.compile(r"/guide/(en|zh|os|console)/([A-Za-z0-9_]+)\.(?:webp|png)")
# The directories whose one image both language pages show.
SHARED_DIRECTORIES = ("os", "console")


def guide_pages() -> list:
    """Every page of the site, as a path relative to the guide.

    Returns:
        Relative paths such as ``hub/install.md`` and ``zh-CN/hub/install.md``.
    """
    pages = []
    for path in sorted(GUIDE_DIR.rglob("*.md")):
        relative = path.relative_to(GUIDE_DIR)
        if relative.parts[0] in SKIPPED_DIRS or str(relative) in SKIPPED_PAGES:
            continue
        pages.append(relative.as_posix())
    return pages


def english_path(page: str) -> str:
    """A page's English path, the key the table uses."""
    return page.removeprefix(CHINESE_PREFIX)


def shot_pages(shot: dict) -> list:
    """The English page paths one entry belongs to: ``page``, then ``pages``.

    Args:
        shot: The shot table's entry.

    Returns:
        The paths in the entry's order, each once.
    """
    pages = [shot["page"]] if "page" in shot else []
    pages.extend(page for page in shot.get("pages", []) if page not in pages)
    return pages


def language_pages(shot: dict) -> list:
    """The pages one language alone shows a shared entry's image on.

    Args:
        shot: The shot table's entry.

    Returns:
        ``(language, page)`` pairs from the entry's ``language_pages``, with
        ``language`` ``en`` or ``zh`` and ``page`` the English page path.
    """
    return [
        (language, page)
        for language, pages in shot.get("language_pages", {}).items()
        for page in pages
    ]


def named_images(table: dict) -> set:
    """Every (page, directory, name) the table names.

    Args:
        table: The parsed ``shots.json``.

    Returns:
        One tuple per image and page it belongs to.
    """
    named = set()
    for shot in table["shots"]:
        name = shot["file"].removesuffix(".png")
        language = shot["language"]
        for page in shot_pages(shot):
            if language == "en" or language in SHARED_DIRECTORIES:
                named.add((page, language, name))
            if language == "zh" or language in SHARED_DIRECTORIES:
                named.add((CHINESE_PREFIX + page, language, name))
        for only, page in language_pages(shot):
            prefix = CHINESE_PREFIX if only == "zh" else ""
            named.add((prefix + page, language, name))
    return named


def referenced_images(pages: list) -> set:
    """Every (page, directory, name) the pages reference.

    Args:
        pages: The pages to read, relative to the guide.

    Returns:
        One tuple per image reference.
    """
    referenced = set()
    for page in pages:
        text = (GUIDE_DIR / page).read_text()
        for directory, name in IMAGE_REFERENCE.findall(text):
            referenced.add((page, directory, name))
    return referenced


def main() -> int:
    """Compare the table with the pages.

    Returns:
        0 when they agree, 1 otherwise.
    """
    table = json.loads(SHOTS_FILE.read_text())
    pending = set(table.get("pending", []))
    pages = [page for page in guide_pages() if english_path(page) not in pending]
    checked = set(pages)
    named = {item for item in named_images(table) if item[0] in checked}
    referenced = referenced_images(pages)
    problems = []
    for page, directory, name in sorted(referenced - named):
        problems.append(
            f"{page}: references /guide/{directory}/{name}, not in shots.json"
        )
    for page, directory, name in sorted(named - referenced):
        problems.append(
            f"{page}: shots.json names {directory}/{name}.png, the page does not use it"
        )
    missing = sorted(
        {
            page
            for shot in table["shots"]
            for page in shot_pages(shot) + [p for _, p in language_pages(shot)]
        }
        - {english_path(page) for page in guide_pages()}
        - pending
    )
    for page in missing:
        problems.append(f"shots.json names page {page}, which does not exist")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(
        f"{len(referenced)} image references match shots.json across {len(pages)} pages"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
