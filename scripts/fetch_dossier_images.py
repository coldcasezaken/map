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

    header_classes = [
        "jw-mobile-logo",
        "jw-mobile-header-image",
        "jw-mobile-header",
        "block-header",
    ]

    for parent in item.get(
        "parents",
        []
    ):

        parent_class = (
            parent.get(
                "class",
                ""
            )
            .lower()
            .split()
        )

        for value in header_classes:

            if value in parent_class:

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


def title_words_for_case(case_title):

    title_lower = case_title.lower()

    words = []

    for word in title_lower.split():

        cleaned = word.strip(
            ".,:;!?()[]{}\"'"
        )

        if len(cleaned) >= 4:

            words.append(cleaned)

    return words


def matching_title_words(
    case_title,
    alt
):

    alt_lower = alt.lower()

    words = title_words_for_case(
        case_title
    )

    matches = []

    for word in words:

        if word in alt_lower:

            matches.append(word)

    return matches


def score_candidate(
    item,
    case_title,
    duplicate_urls
):

    url = item["url"]
    alt = item.get(
        "alt",
        ""
    )

    width = number(
        item.get("width")
    )

    height = number(
        item.get("height")
    )

    score = 0
    reasons = []

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

    if is_content_image(item):

        score += 20

        reasons.append(
            "JouwWeb content-afbeelding"
        )

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

    matches = matching_title_words(
        case_title,
        alt
    )

    if matches:

        score += (
            len(matches) * 20
        )

        reasons.append(
            "alt-tekst past bij dossier"
        )

    if width and height:

        ratio = width / height

        if 0.55 <= ratio <= 1.15:

            score += 15

            reasons.append(
                "geschikte portretverhouding"
            )

    duplicate_count = duplicate_urls.get(
        normalise_url(url),
        0
    )

    if duplicate_count > 1:

        reasons.append(
            f"gedeeld door {duplicate_count} dossiers"
        )

        if not matches:

            return -500, [
                "gedeelde afbeelding zonder "
                "dossier-specifieke alt-tekst"
            ]

        score -= 40

    if has_unwanted_filename(url):

        score -= 100

        reasons.append(
            "technische/tijdlijn-bestandsnaam"
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


with open(
    CASES_FILE,
    "r",
    encoding="utf-8"
) as file:

    cases = json.load(file)


only = os.environ.get(
    "ONLY_SLUGS",
    ""
).strip().lower()

wanted = [
    item.strip()
    for item in only.split(",")
    if item.strip()
]


print("")
print(
    "=============================================="
)

print(
    " AUTOMATISCHE FOTOSELECTIE — VOLLEDIGE DIAGNOSE"
)

print(
    "=============================================="
)

print("")

if wanted:

    print(
        "Beperkte test:",
        ", ".join(wanted)
    )

else:

    print(
        "Alle dossiers worden onderzocht."
    )

print("")

print(
    "BELANGRIJK: cases.json wordt NIET gewijzigd."
)

print("")


selected_cases = []

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

    if wanted and slug not in wanted:
        continue

    selected_cases.append(
        {
            "case": case,
            "slug": slug,
        }
    )


print(
    f"Dossiers te onderzoeken: {len(selected_cases)}"
)

print("")


scanned = []

errors = []

for number_index, entry in enumerate(
    selected_cases,
    1
):

    case = entry["case"]
    slug = entry["slug"]

    print(
        f"[{number_index}/{len(selected_cases)}] CHECK {slug}"
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

        errors.append(
            {
                "slug": slug,
                "error": str(error),
            }
        )

        print(
            f"[ERROR] {slug}: {error}"
        )

    time.sleep(0.5)


image_dossiers = {}

image_details = {}

for result in scanned:

    slug = result["slug"]

    for item in result["images"]:

        if is_social_or_tracking(
            item["url"]
        ):

            continue

        key = normalise_url(
            item["url"]
        )

        if key not in image_dossiers:

            image_dossiers[key] = set()

        image_dossiers[key].add(slug)

        if key not in image_details:

            image_details[key] = {
                "url": item["url"],
                "alt": item.get(
                    "alt",
                    ""
                ),
            }


duplicate_urls = {
    key: len(slugs)
    for key, slugs in image_dossiers.items()
}


chosen = []

no_photo = []

shared_candidates = []


for result in scanned:

    case = result["case"]
    slug = result["slug"]
    images = result["images"]

    candidates = choose_best_image(
        case,
        images,
        duplicate_urls
    )

    if candidates:

        best = candidates[0]

        chosen.append(
            {
                "slug": slug,
                "url": best["url"],
                "score": best["score"],
                "reasons": best["reasons"],
            }
        )

    else:

        no_photo.append(
            slug
        )

    for item in images:

        normalised = normalise_url(
            item["url"]
        )

        count = duplicate_urls.get(
            normalised,
            0
        )

        if count > 1:

            shared_candidates.append(
                {
                    "slug": slug,
                    "url": item["url"],
                    "count": count,
                    "alt": item.get(
                        "alt",
                        ""
                    ),
                }
            )


shared_unique = {}

for item in shared_candidates:

    key = normalise_url(
        item["url"]
    )

    if key not in shared_unique:

        shared_unique[key] = {
            "url": item["url"],
            "count": item["count"],
            "alt": item.get(
                "alt",
                ""
            ),
            "dossiers": [],
        }

    if item["slug"] not in shared_unique[key]["dossiers"]:

        shared_unique[key]["dossiers"].append(
            item["slug"]
        )


print("")
print("")
print(
    "=============================================="
)

print(
    " SAMENVATTING"
)

print(
    "=============================================="
)

print("")

print(
    f"Dossiers onderzocht : {len(scanned)}"
)

print(
    f"Automatisch gekozen : {len(chosen)}"
)

print(
    f"GEEN FOTO           : {len(no_photo)}"
)

print(
    f"Fouten              : {len(errors)}"
)

print(
    f"Gedeelde afbeeldingen: "
    f"{len(shared_unique)}"
)

print("")


print(
    "=== AUTOMATISCH GEKOZEN ==="
)

print("")

for item in chosen:

    print(
        f"[PHOTO] {item['slug']}"
    )

    print(
        f"        SCORE: {item['score']}"
    )

    print(
        f"        URL: {item['url']}"
    )

    print(
        "        REDENEN: "
        + ", ".join(
            item["reasons"]
        )
    )

    print("")


print(
    "=== GEEN FOTO ==="
)

print("")

for slug in no_photo:

    print(
        f"[NONE] {slug}"
    )

print("")


print(
    "=== GEDEELDE AFBEELDINGEN ==="
)

print("")

if not shared_unique:

    print(
        "Geen gedeelde afbeeldingen gevonden."
    )

else:

    for item in sorted(
        shared_unique.values(),
        key=lambda value: value["count"],
        reverse=True
    ):

        print(
            f"[SHARED] gebruikt door "
            f"{item['count']} dossiers"
        )

        print(
            f"URL: {item['url']}"
        )

        print(
            f"ALT: {item['alt']}"
        )

        print(
            "DOSSIERS: "
            + ", ".join(
                item["dossiers"]
            )
        )

        print("")


if errors:

    print(
        "=== FOUTEN ==="
    )

    print("")

    for error in errors:

        print(
            f"[ERROR] {error['slug']}"
        )

        print(
            f"        {error['error']}"
        )

        print("")


print(
    "=============================================="
)

print(
    " TEST KLAAR"
)

print(
    "=============================================="
)

print("")

print(
    "Er zijn GEEN wijzigingen opgeslagen "
    "in cases.json."
)

print(
    "Deze run was alleen een diagnose."
)

print("")
