import json
import os
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


CASES_FILE = "cases.json"


class ImageParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.images = []

        # Houd bij in welke HTML-elementen een afbeelding staat.
        self.stack = []

    def handle_starttag(self, tag, attrs):

        attrs_dict = dict(attrs)

        tag = tag.lower()

        # Bewaar de context van het huidige element.
        context = {
            "tag": tag,
            "id": attrs_dict.get("id", ""),
            "class": attrs_dict.get("class", ""),
        }

        self.stack.append(context)

        if tag != "img":
            return

        # Zoek alle mogelijke afbeeldingsbronnen.
        image_sources = []

        for key in (
            "src",
            "data-src",
            "data-original",
            "data-lazy-src",
        ):
            value = attrs_dict.get(key)

            if value:
                image_sources.append(value)

        if not image_sources:
            return

        image = image_sources[0]

        alt = attrs_dict.get("alt", "")

        # Bewaar de HTML-context rondom de afbeelding.
        parents = []

        for item in self.stack[:-1]:
            parents.append(
                {
                    "tag": item["tag"],
                    "id": item["id"],
                    "class": item["class"],
                }
            )

        self.images.append(
            {
                "src": image,
                "alt": alt,
                "width": attrs_dict.get("width", ""),
                "height": attrs_dict.get("height", ""),
                "class": attrs_dict.get("class", ""),
                "id": attrs_dict.get("id", ""),
                "parents": parents,
            }
        )

    def handle_endtag(self, tag):

        tag = tag.lower()

        # Haal het meest recente element van dezelfde tag uit de stack.
        for index in range(len(self.stack) - 1, -1, -1):

            if self.stack[index]["tag"] == tag:
                self.stack = self.stack[:index]
                return


def fetch_page(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ColdcaseExplorer"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


def is_good_image(url):

    if not url.startswith(
        ("http://", "https://")
    ):
        return False

    text = url.lower()

    unwanted = [
        "logo",
        "favicon",
        "icon",
        "sprite",
        "placeholder",
        "cookie",
        "marker",
        "cluster",
        "facebook",
        "instagram",
        "linkedin",
        "youtube",
    ]

    for word in unwanted:

        if word in text:
            return False

    return True


def print_context(item):

    print("  CONTEXT:")

    parents = item.get("parents", [])

    # Laat maximaal de laatste 8 ouders zien.
    for parent in parents[-8:]:

        tag = parent.get("tag", "")
        element_id = parent.get("id", "")
        element_class = parent.get("class", "")

        line = "    <" + tag

        if element_id:
            line += " id=\"" + element_id + "\""

        if element_class:
            line += " class=\"" + element_class + "\""

        line += ">"

        print(line)


def find_image(page_url, html):

    parser = ImageParser()
    parser.feed(html)

    print("")
    print("=== AFBEELDINGEN GEVONDEN ===")
    print(f"Pagina: {page_url}")
    print(f"Aantal: {len(parser.images)}")
    print("")

    for number, item in enumerate(
        parser.images,
        1
    ):

        url = urljoin(
            page_url,
            item["src"]
        )

        print(
            f"[IMAGE {number}]"
        )

        print(
            f"URL    : {url}"
        )

        print(
            f"ALT    : {item['alt']}"
        )

        print(
            f"CLASS  : {item['class']}"
        )

        print(
            f"ID     : {item['id']}"
        )

        print(
            f"WIDTH  : {item['width']}"
        )

        print(
            f"HEIGHT : {item['height']}"
        )

        print_context(item)

        print("")

    print(
        "=== EINDE AFBEELDINGEN ==="
    )

    print("")

    # BELANGRIJK:
    # Deze test kiest bewust nog GEEN afbeelding.
    return None


with open(
    CASES_FILE,
    "r",
    encoding="utf-8"
) as file:

    cases = json.load(file)


only = os.environ.get(
    "ONLY_SLUGS",
    "ingrid-hakkert"
).strip().lower()


wanted = [
    item.strip()
    for item in only.split(",")
    if item.strip()
]


changed = 0


for case in cases:

    link = str(
        case.get("link") or ""
    ).strip()

    if not link:
        continue

    if "/zaak-zonder-dossier" in link.lower():
        continue

    slug = (
        urlparse(link)
        .path
        .rstrip("/")
        .split("/")[-1]
        .lower()
    )

    # Bestaande handmatige foto nooit overschrijven.
    if "image" in case:

        print(
            f"[SKIP] {slug}: image bestaat al"
        )

        continue

    if wanted and slug not in wanted:
        continue

    print(
        f"[CHECK] {slug}"
    )

    try:

        html = fetch_page(link)

        image = find_image(
            link,
            html
        )

        if image:

            case["image"] = image

            changed += 1

            print(
                f"[FOUND] {image}"
            )

        else:

            print(
                "[NONE] Geen geschikte foto gevonden"
            )

    except Exception as error:

        print(
            f"[ERROR] {error}"
        )

    time.sleep(1)


if changed:

    with open(
        CASES_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            cases,
            file,
            ensure_ascii=False,
            indent=2
        )

        file.write("\n")


print(
    f"Klaar. {changed} foto('s) toegevoegd."
)
