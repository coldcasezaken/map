import json
import os
import time
import urllib.request
from collections import Counter
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

        self.images.append(
            {
                "src": image_sources[0],
                "alt": attrs_dict.get("alt", ""),
                "width": attrs_dict.get("width", ""),
                "height": attrs_dict.get("height", ""),
                "class": attrs_dict.get("class", ""),
                "id": attrs_dict.get("id", ""),
                "parents": [
                    {
                        "tag": item["tag"],
                        "id": item["id"],
                        "class": item["class"],
                    }
                    for item in self.stack[:-1]
                ],
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


def number(value):

    try:
        return float(value)
    except Exception:
        return 0


def normalise_url(url):

    parsed = urlparse(url)

    return (
        parsed.scheme.lower()
        + "://"
        + parsed.netloc.lower()
        + parsed.path
    )


def is_social_or_tracking(url):

    text = url.lower()

    unwanted_domains = [
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "google-analytics.com",
    ]

    return any(
        domain in text
        for domain in unwanted_domains
    )


def has_unwanted_filename(url):

    text = url.lower()

    unwanted = [
        "logo",
        "favicon",
        "sprite",
        "placeholder",
        "marker",
        "cluster",
        "cookie",
        "tijdlijn",
        "timeline",
    ]

    return any(
        word in text
        for word in unwanted
    )


def is_header_image(item):

    # Alleen heel specifieke header/logo-elementen
    # gelden als header.
    header_classes = [
        "jw-mobile-logo",
        "jw-mobile-header-image",
        "jw-mobile-header",
        "block-header",
    ]

    # BELANGRIJK:
    # id="top" staat op de body van de hele pagina
    # en mag daarom NIET als header gelden.
    header_ids = []

    for parent in item.get("parents", []):

        parent_class = (
            parent.get("class", "")
            .lower()
            .split()
        )

        parent_id = (
            parent.get("id", "")
            .lower()
        )

        for value in header_classes:

            if value in parent_class:
                return True

        if parent_id in header_ids:
            return True

    return False


def is_content_image(item):

    combined = ""

    for parent in item.get(
        "parents",
        []
    ):

        combined += (
            " "
            + parent.get("class", "")
            + " "
            + parent.get("id", "")
        ).lower()

    combined += (
        " "
        + item.get("class", "")
        + " "
        + item.get("id", "")
    ).lower()

    return (
        "jw-element-image" in combined
    )


def score_candidate(
    item,
    case_title,
    duplicate_urls
):

    url = item["url"]
    alt = item.get("alt", "")

    width = number(
        item.get("width")
    )

    height = number(
        item.get("height")
    )

    score = 0
    reasons = []

    # ---------------------------------------------
    # Technische afbeeldingen uitsluiten
    # ---------------------------------------------

    if is_social_or_tracking(url):

        return -1000, [
            "social/tracking"
        ]

    if is_header_image(item):

        return -1000, [
            "header/logo"
        ]

    if width == 1 and height == 1:

        return -1000, [
            "1x1 tracking pixel"
        ]

    if width and height:

        if width < 200 or height < 200:

            return -1000, [
                "te klein"
            ]

    # ---------------------------------------------
    # JouwWeb content-afbeelding
    # ---------------------------------------------

    if is_content_image(item):

        score += 20

        reasons.append(
            "JouwWeb content-afbeelding"
        )

    # ---------------------------------------------
    # Afmetingen
    # ---------------------------------------------

    area = width * height

    if area >= 500000:

        score += 20

        reasons.append(
            "grote afbeelding"
        )

    elif area >= 250000:

        score += 10

        reasons.append(
            "voldoende groot"
        )

    # ---------------------------------------------
    # Gedeelde afbeelding
    # ---------------------------------------------

    if duplicate_urls.get(
        normalise_url(url),
        0
    ) > 1:

        score -= 80

        reasons.append(
            "komt bij meerdere dossiers voor"
        )

    # ---------------------------------------------
    # Bestandsnaam
    # ---------------------------------------------

    if has_unwanted_filename(url):

        score -= 100

        reasons.append(
            "technische/tijdlijn-bestandsnaam"
        )

    # ---------------------------------------------
    # ALT-tekst
    # ---------------------------------------------

    alt_lower = alt.lower()
    title_lower = case_title.lower()

    title_words = [
        word.strip(
            ".,:;!?()[]{}"
        )
        for word in title_lower.split()
        if len(word) >= 4
    ]

    matching_words = 0

    for word in title_words:

        if word in alt_lower:
            matching_words += 1

    if matching_words:

        score += (
            matching_words * 20
        )

        reasons.append(
            "alt-tekst past bij dossier"
        )

    # ---------------------------------------------
    # Geschikte verhouding
    # ---------------------------------------------

    if width and height:

        ratio = width / height

        if 0.55 <= ratio <= 1.15:

            score += 15

            reasons.append(
                "geschikte portretverhouding"
            )

    return score, reasons


def choose_best_image(
    case,
    images,
    duplicate_urls
):

    candidates = []

    title = str(
        case.get("title")
        or case.get("name")
        or ""
    )

    for item in images:

        score, reasons = score_candidate(
            item,
            title,
            duplicate_urls
        )

        item["score"] = score
        item["reasons"] = reasons

        if score > 0:

            candidates.append(item)

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return candidates


def print_images(
    case,
    images,
    duplicate_urls
):

    title = str(
        case.get("title")
        or case.get("name")
        or ""
    )

    print("")
    print(
        "=== AFBEELDINGEN GEVONDEN ==="
    )

    print(
        f"Dossier: {title}"
    )

    print(
        f"Pagina: {case.get('link', '')}"
    )

    print(
        f"Aantal: {len(images)}"
    )

    print("")

    for number, item in enumerate(
        images,
        1
    ):

        score, reasons = score_candidate(
            item,
            title,
            duplicate_urls
        )

        print(
            f"[IMAGE {number}]"
        )

        print(
            f"URL    : {item['url']}"
        )

        print(
            f"ALT    : {item['alt']}"
        )

        print(
            f"WIDTH  : {item['width']}"
        )

        print(
            f"HEIGHT : {item['height']}"
        )

        print(
            f"SCORE  : {score}"
        )

        if reasons:

            print(
                "REDENEN: "
                + ", ".join(reasons)
            )

        else:

            print(
                "REDENEN: geen"
            )

        print("")


def scan_case(case):

    link = str(
        case.get("link")
        or ""
    ).strip()

    html = fetch_page(link)

    parser = ImageParser()
    parser.feed(html)

    images = []

    for item in parser.images:

        item = dict(item)

        item["url"] = urljoin(
            link,
            item["src"]
        )

        images.append(item)

    return images


# -------------------------------------------------
# cases.json laden
# -------------------------------------------------

with open(
    CASES_FILE,
    "r",
    encoding="utf-8"
) as file:

    cases = json.load(file)


# -------------------------------------------------
# Alleen de drie testdossiers
# -------------------------------------------------

only = os.environ.get(
    "ONLY_SLUGS",
    ""
).strip().lower()

if not only:

    only = (
        "john-yellowley,"
        "ingrid-hakkert,"
        "monika-tanova"
    )


wanted = [
    item.strip()
    for item in only.split(",")
    if item.strip()
]


print("")
print(
    "=== AUTOMATISCHE FOTOSELECTIE — DIAGNOSE ==="
)

print(
    "Te onderzoeken dossiers:",
    ", ".join(wanted)
)

print("")


# -------------------------------------------------
# Dossiers scannen
# -------------------------------------------------

scanned = []


for case in cases:

    link = str(
        case.get("link")
        or ""
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

    if slug not in wanted:
        continue

    print(
        f"[CHECK] {slug}"
    )

    try:

        images = scan_case(case)

        scanned.append(
            {
                "case": case,
                "slug": slug,
                "images": images,
            }
        )

    except Exception as error:

        print(
            f"[ERROR] {slug}: {error}"
        )

    time.sleep(1)


# -------------------------------------------------
# Gedeelde afbeeldingen bepalen
# -------------------------------------------------

all_urls = []

for result in scanned:

    for item in result["images"]:

        if is_social_or_tracking(
            item["url"]
        ):
            continue

        all_urls.append(
            normalise_url(
                item["url"]
            )
        )


duplicate_urls = Counter(
    all_urls
)


print("")
print(
    "=== GEDEELDE AFBEELDINGEN ==="
)

for url, count in duplicate_urls.items():

    if count > 1:

        print(
            f"[SHARED {count}x] {url}"
        )

print("")


# -------------------------------------------------
# Beste kandidaat per dossier
# -------------------------------------------------

for result in scanned:

    case = result["case"]
    slug = result["slug"]
    images = result["images"]

    print("")
    print(
        "========================================"
    )

    print(
        f"DOSSIER: {slug}"
    )

    print(
        "========================================"
    )

    print_images(
        case,
        images,
        duplicate_urls
    )

    candidates = choose_best_image(
        case,
        images,
        duplicate_urls
    )

    if not candidates:

        print(
            "[RESULTAAT] GEEN FOTO"
        )

        print(
            "Geen betrouwbare kandidaat gevonden."
        )

        continue

    best = candidates[0]

    print(
        "[RESULTAAT] AUTOMATISCH GEKOZEN"
    )

    print(
        f"URL   : {best['url']}"
    )

    print(
        f"SCORE : {best['score']}"
    )

    print(
        "REDENEN: "
        + ", ".join(
            best["reasons"]
        )
    )

    print("")


# -------------------------------------------------
# VEILIGHEID
# -------------------------------------------------

print("")
print(
    "=== TEST KLAAR ==="
)

print(
    "Er zijn geen wijzigingen opgeslagen in cases.json."
)

print("")
