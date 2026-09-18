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
        self.meta_images = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag.lower() == "img":
            for key in (
                "src",
                "data-src",
                "data-original",
                "data-lazy-src",
            ):
                value = attrs.get(key)
                if value:
                    self.images.append(
                        (value, attrs.get("alt", ""))
                    )

        if tag.lower() == "meta":
            prop = (
                attrs.get("property")
                or attrs.get("name")
                or ""
            ).lower()

            content = attrs.get("content")

            if prop in (
                "og:image",
                "twitter:image",
                "twitter:image:src",
            ) and content:
                self.meta_images.append(content)


def fetch_page(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 ColdcaseExplorer"
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
    if not url.startswith(("http://", "https://")):
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


def score_image(url, alt=""):
    text = (
        url + " " + alt
    ).lower()

    score = 0

    if "jwwb.nl" in text:
        score += 10

    if "/public/" in text:
        score += 5

    if "high" in text:
        score += 5

    if any(word in text for word in [
        "portret",
        "persoon",
        "slachtoffer",
        "vermist",
        "dossier",
        "moord",
    ]):
        score += 3

    return score


def find_image(page_url, html):
    parser = ImageParser()
    parser.feed(html)

    print("")
    print("=== AFBEELDINGEN GEVONDEN ===")
    print(f"Pagina: {page_url}")
    print(f"Aantal: {len(parser.images)}")
    print("")

    for number, (image, alt) in enumerate(parser.images, 1):
        url = urljoin(page_url, image)

        print(f"[IMAGE {number}]")
        print(f"URL : {url}")
        print(f"ALT : {alt}")
        print("")

    print("=== EINDE AFBEELDINGEN ===")
    print("")

    # Tijdelijk alleen rapporteren.
    # Er wordt bewust geen afbeelding gekozen.
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

    # Bestaande handmatige foto nooit overschrijven
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
