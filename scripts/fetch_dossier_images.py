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
        self.stack = []

    def handle_starttag(self, tag, attrs):

        attrs_dict = dict(attrs)

        tag = tag.lower()

        context = {
            "tag": tag,
            "id": attrs_dict.get("id", ""),
            "class": attrs_dict.get("class", ""),
        }

        self.stack.append(context)

        if tag != "img":
            return

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

        for index in range(
            len(self.stack) - 1,
            -1,
            -1
        ):

            if self.stack[index]["tag"] == tag:

                self.stack = self.stack[:index]

                return


def fetch_page(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ColdcaseExplorer"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


def print_context(item):

    print("  CONTEXT:")

    parents = item.get("parents", [])

    for parent in parents[-8:]:

        tag = parent.get("tag", "")
        element_id = parent.get("id", "")
        element_class = parent.get("class", "")

        line = "    <" + tag

        if element_id:
            line += ' id="' + element_id + '"'

        if element_class:
            line += ' class="' + element_class + '"'

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

    # DIAGNOSTISCHE TEST:
    # Bewust geen afbeelding kiezen.
    # Er wordt niets aan cases.json toegevoegd.
    return None


with open(
    CASES_FILE,
    "r",
    encoding="utf-8"
) as file:

    cases = json.load(file)


# Als Actions geen ONLY_SLUGS meegeeft,
# testen we standaard alleen John en Ingrid.
only = os.environ.get(
    "ONLY_SLUGS",
    ""
).strip().lower()

if not only:
    only = "john-yellowley,ingrid-hakkert"


wanted = [
    item.strip()
    for item in only.split(",")
    if item.strip()
]


print("")
print("=== DIAGNOSTISCHE TEST ===")
print(
    "Te onderzoeken dossiers:",
    ", ".join(wanted)
)
print("")


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

    # Alleen de opgegeven dossiers onderzoeken.
    if slug not in wanted:
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

        # In deze test wordt bewust niets opgeslagen.
        if image:

            print(
                f"[FOUND] {image}"
            )

        else:

            print(
                "[NONE] Geen afbeelding automatisch gekozen"
            )

    except Exception as error:

        print(
            f"[ERROR] {error}"
        )

    time.sleep(1)


print("")
print(
    f"Klaar. {changed} foto('s) toegevoegd."
)
print("")
