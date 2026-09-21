import json
import os
import re
import time
import unicodedata
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


CASES_FILE = "cases.json"

GENERAL_SHARED_LIMIT = 50


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
            ". ,:;!?()[]{}\"'"
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

    if has_unwanted_filename(url):

        return -1000, [
            "technische/logo-bestandsnaam"
        ]

    duplicate_count = duplicate_urls.get(
        normalise_url(url),
        0
    )

    if duplicate_count > GENERAL_SHARED_LIMIT:

        return -1000, [
            f"algemene afbeelding gebruikt door "
            f"{duplicate_count} dossiers"
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

    if duplicate_count == 1:

        score += 20

        reasons.append(
            "alleen gebruikt door dit dossier"
        )

    elif duplicate_count > 1:

        reasons.append(
            f"gedeeld door {duplicate_count} dossiers"
        )

        score -= 40

        if not matches:

            return -500, [
                "gedeelde afbeelding zonder "
                "dossier-specifieke alt-tekst"
            ]

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


def make_case_id(case):

    title = str(
        case.get("title")
        or case.get("name")
        or ""
    ).strip()

    if not title:
        return ""

    text = title

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.lower()

    prefixes = [
        "de vermissing van de ",
        "de vermissing van ",
        "de moord op de ",
        "de moord op ",
        "de verdwijning van de ",
        "de verdwijning van ",
        "de dood van de ",
        "de dood van ",
        "de zaak van de ",
        "de zaak van ",
    ]

    for prefix in prefixes:

        if text.startswith(prefix):

            text = text[
                len(prefix):
            ]

            break

    text = re.sub(
        r"\s+(?:19|20)\d{2}$",
        "",
        text
    )

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text
    )

    text = re.sub(
        r"-+",
        "-",
        text
    )

    text = text.strip("-")

    return text


# ==============================================
# CASES.JSON INLEZEN
# ==============================================

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
    " AUTOMATISCHE DOSSIERFOTO + ID — TEST V3"
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
    "Algemene afbeeldingen > "
    f"{GENERAL_SHARED_LIMIT} dossiers worden uitgesloten."
)

print("")

print(
    "Bestaande handmatige foto's worden nooit "
    "overschreven."
)

print("")


# ==============================================
# UNIEKE ID'S MAKEN
# ==============================================

id_map = {}

id_collisions = []

for index, case in enumerate(cases):

    existing_id = str(
        case.get("id")
        or ""
    ).strip()

    if existing_id:

        base_id = existing_id

    else:

        base_id = make_case_id(
            case
        )

    if not base_id:
        continue

    case_id = base_id

    counter = 2

    while case_id in id_map:

        case_id = f"{base_id}-{counter}"

        counter += 1

    # BELANGRIJK:
    # De unieke ID wordt altijd teruggeschreven
    # naar het record, ook wanneer er al een ID
    # aanwezig was maar die dubbel bleek te zijn.

    case["id"] = case_id

    id_map[case_id] = index


print(
    f"ID's aanwezig/gemaakt: "
    f"{len(id_map)}"
)

print(
    f"ID-dubbelingen: "
    f"{len(id_collisions)}"
)

print("")


# ==============================================
# DOSSIERS SELECTEREN
# ==============================================

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
    f"Dossiers met sitepagina te onderzoeken: "
    f"{len(selected_cases)}"
)

print("")


# ==============================================
# DOSSIERS SCANNEN
# ==============================================

scanned = []

errors = []

for number_index, entry in enumerate(
    selected_cases,
    1
):

    case = entry["case"]

    slug = entry["slug"]

    print(
        f"[{number_index}/{len(selected_cases)}] "
        f"CHECK {slug}"
    )

    try:

        images = scan_case(
            case
        )

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


# ==============================================
# GEDEELDE AFBEELDINGEN
# ==============================================

image_dossiers = {}

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

        image_dossiers[key].add(
            slug
        )


duplicate_urls = {
    key: len(slugs)
    for key, slugs in image_dossiers.items()
}


# ==============================================
# FOTO'S KIEZEN
# ==============================================

chosen = []

no_photo = []

manual_images = []

new_images = []


for result in scanned:

    case = result["case"]

    slug = result["slug"]

    images = result["images"]

    existing_image = str(
        case.get("image")
        or ""
    ).strip()

    if existing_image:

        manual_images.append(
            {
                "slug": slug,
                "url": existing_image,
            }
        )

        print(
            f"[KEEP IMAGE] {slug}"
        )

        continue

    candidates = choose_best_image(
        case,
        images,
        duplicate_urls
    )

    if candidates:

        best = candidates[0]

        case["image"] = best["url"]

        new_images.append(
            {
                "slug": slug,
                "url": best["url"],
                "score": best["score"],
                "reasons": best["reasons"],
            }
        )

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


# ==============================================
# BELANGRIJK:
# CASES.JSON DAADWERKELIJK OPSLAAN
# ==============================================

with open(
    CASES_FILE,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        cases,
        file,
        ensure_ascii=False,
        separators=(",", ":")
    )

    file.write("\n")


print("")
print(
    "cases.json is daadwerkelijk opgeslagen."
)
print("")


# ==============================================
# SAMENVATTING
# ==============================================

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
    f"Totaal records       : {len(cases)}"
)

print(
    f"ID's aanwezig        : {len(id_map)}"
)

print(
    f"Dossiers onderzocht  : {len(scanned)}"
)

print(
    f"Nieuwe foto's        : {len(new_images)}"
)

print(
    f"Bestaande foto's     : {len(manual_images)}"
)

print(
    f"GEEN FOTO            : {len(no_photo)}"
)

print(
    f"Fouten               : {len(errors)}"
)

print(
    f"ID-dubbelingen       : {len(id_collisions)}"
)

print("")


# ==============================================
# NIEUWE FOTO'S
# ==============================================

print(
    "=== NIEUW AUTOMATISCH GEKOZEN ==="
)

print("")

for item in new_images:

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


# ==============================================
# BESTAANDE FOTO'S
# ==============================================

print(
    "=== BESTAANDE FOTO'S BEHOUDEN ==="
)

print("")

for item in manual_images:

    print(
        f"[KEEP IMAGE] {item['slug']}"
    )

    print(
        f"        URL: {item['url']}"
    )

    print("")


# ==============================================
# GEEN FOTO
# ==============================================

print(
    "=== GEEN FOTO ==="
)

print("")

for slug in no_photo:

    print(
        f"[NONE] {slug}"
    )

print("")


# ==============================================
# FOUTEN
# ==============================================

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
    "cases.json is aangepast op de TESTBRANCH."
)

print(
    "De workflow kan deze wijzigingen committen."
)

print("")
