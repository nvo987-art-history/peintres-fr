import json
import ssl
import time
import urllib.parse
import urllib.request

OUTPUT_FILE = "painters.json"

WIKIPEDIA_API = "https://fr.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

USER_AGENT = (
    "FrenchPaintersBot/1.0 "
    "(https://github.com/nvo987-art-history/peintres-fr; contact@example.com)"
)

ssl_context = ssl.create_default_context()


def log(msg):
    """Azonnali konzolra írás GitHub Actions-ben."""
    print(msg, flush=True)


def api_request(url, params, retries=3):
    """Általános MediaWiki API lekérés."""
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        }
    )

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(
                req,
                timeout=60,
                context=ssl_context
            ) as response:
                content = response.read().decode(
                    "utf-8",
                    errors="replace"
                )

                return json.loads(content, strict=False)

        except Exception as e:
            log(
                f"  [Újrapróbálkozás {attempt}/{retries}] "
                f"Hiba: {e}"
            )

            if attempt < retries:
                time.sleep(4 * attempt)

    return None


def fetch_category_members(category, retries=3):
    """
    A francia Wikipédia kategória teljes tartalmának lekérése,
    beleértve az alkategóriákat is.
    """

    pages = []
    subcategories = []

    cmcontinue = None

    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": "0|14",
            "cmprop": "title|type",
            "cmlimit": "500",
            "format": "json"
        }

        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        data = api_request(
            WIKIPEDIA_API,
            params,
            retries
        )

        if not data:
            return None, None

        members = data.get(
            "query",
            {}
        ).get(
            "categorymembers",
            []
        )

        for member in members:
            title = member.get("title", "").strip()
            member_type = member.get("type", "")

            if not title:
                continue

            if member_type == "subcat":
                subcategories.append(title)

            elif member_type == "page":
                pages.append(title)

        if "continue" not in data:
            break

        cmcontinue = data["continue"].get("cmcontinue")

        if not cmcontinue:
            break

    return pages, subcategories


def fetch_all_painter_pages():
    """
    A Catégorie:Peintre français teljes kategóriafájának
    bejárása.
    """

    root_category = "Catégorie:Peintre français"

    all_pages = set()
    categories_to_visit = [root_category]
    visited_categories = set()

    while categories_to_visit:

        category = categories_to_visit.pop()

        if category in visited_categories:
            continue

        visited_categories.add(category)

        log(
            f"Kategória lekérése: {category}"
        )

        pages, subcategories = fetch_category_members(category)

        if pages is None:
            log(
                f"HIBA: nem sikerült lekérni: {category}"
            )
            continue

        log(
            f"  -> {len(pages)} oldal, "
            f"{len(subcategories)} alkategória"
        )

        for page in pages:
            all_pages.add(page)

        for subcategory in subcategories:
            if subcategory not in visited_categories:
                categories_to_visit.append(subcategory)

        time.sleep(0.2)

    return sorted(all_pages)


def fetch_wikidata_ids(page_titles):
    """
    A francia Wikipédia oldalakból lekéri a Wikidata QID-ket.
    """

    result = {}

    batch_size = 50

    for start in range(0, len(page_titles), batch_size):
        batch = page_titles[
            start:start + batch_size
        ]

        titles = "|".join(batch)

        params = {
            "action": "query",
            "titles": titles,
            "prop": "pageprops",
            "ppprop": "wikibase_item",
            "format": "json"
        }

        data = api_request(
            WIKIPEDIA_API,
            params
        )

        if not data:
            log(
                f"HIBA: nem sikerült lekérni "
                f"{len(batch)} Wikipédia-oldalt."
            )
            continue

        pages = data.get(
            "query",
            {}
        ).get(
            "pages",
            {}
        )

        for page in pages.values():

            title = page.get(
                "title",
                ""
            ).strip()

            pageprops = page.get(
                "pageprops",
                {}
            )

            qid = pageprops.get(
                "wikibase_item",
                ""
            ).strip()

            if (
                title
                and qid
                and qid.startswith("Q")
            ):
                result[title] = qid

        log(
            f"Wikidata QID-k: "
            f"{min(start + batch_size, len(page_titles))}"
            f"/{len(page_titles)}"
        )

        time.sleep(0.2)

    return result


def fetch_websites(qids):
    """
    Wikidatából csak a P856 (official website)
    adatot kérjük le.
    """

    websites = {}

    batch_size = 50

    qid_list = sorted(qids)

    for start in range(0, len(qid_list), batch_size):

        batch = qid_list[
            start:start + batch_size
        ]

        params = {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "claims",
            "format": "json"
        }

        data = api_request(
            WIKIDATA_API,
            params
        )

        if not data:
            log(
                f"HIBA: nem sikerült lekérni "
                f"{len(batch)} Wikidata-elemet."
            )
            continue

        entities = data.get(
            "entities",
            {}
        )

        for qid, entity in entities.items():

            claims = entity.get(
                "claims",
                {}
            )

            p856_claims = claims.get(
                "P856",
                []
            )

            website = ""

            for claim in p856_claims:

                mainsnak = claim.get(
                    "mainsnak",
                    {}
                )

                if mainsnak.get(
                    "snaktype"
                ) != "value":
                    continue

                datavalue = mainsnak.get(
                    "datavalue",
                    {}
                )

                value = datavalue.get(
                    "value"
                )

                if isinstance(value, str) and value.strip():
                    website = value.strip()
                    break

            websites[qid] = website

        log(
            f"Website adatok: "
            f"{min(start + batch_size, len(qid_list))}"
            f"/{len(qid_list)}"
        )

        time.sleep(0.2)

    return websites


def main():

    log("Francia festők adatainak lekérése...")
    log("Forrás: fr.wikipedia.org - Catégorie:Peintre français")

    # ---------------------------------------------------------
    # 1. Francia festői kategória teljes bejárása
    # ---------------------------------------------------------

    wikipedia_pages = fetch_all_painter_pages()

    if not wikipedia_pages:
        log("HIBA: egyetlen festői Wikipédia-oldal sem érkezett.")
        raise RuntimeError(
            "A Wikipédia API nem adott vissza festői oldalakat."
        )

    log(
        f"Összes egyedi Wikipédia-oldal: "
        f"{len(wikipedia_pages)}"
    )

    # ---------------------------------------------------------
    # 2. Wikipédia -> Wikidata QID
    # ---------------------------------------------------------

    page_qids = fetch_wikidata_ids(
        wikipedia_pages
    )

    if not page_qids:
        log("HIBA: nem sikerült Wikidata QID-ket találni.")
        raise RuntimeError(
            "Nem sikerült Wikidata QID-ket lekérni."
        )

    log(
        f"Összes Wikidata-azonosító: "
        f"{len(page_qids)}"
    )

    # ---------------------------------------------------------
    # 3. Wikidata -> official website (P856)
    # ---------------------------------------------------------

    qids = set(
        page_qids.values()
    )

    websites = fetch_websites(
        qids
    )

    # ---------------------------------------------------------
    # 4. Végső adatok
    # ---------------------------------------------------------

    painters_map = {}

    for wikipedia_title, qid in page_qids.items():

        name = wikipedia_title.strip()

        wikipedia_url = (
            "https://fr.wikipedia.org/wiki/"
            + urllib.parse.quote(
                wikipedia_title.replace(" ", "_"),
                safe="/():,'-"
            )
        )

        website = websites.get(
            qid,
            ""
        )

        painters_map[qid] = {
            "name": name,
            "wikidata": (
                f"https://www.wikidata.org/wiki/{qid}"
            ),
            "wikipedia": wikipedia_url,
            "website": website
        }

    # ---------------------------------------------------------
    # 5. Rendezés név szerint
    # ---------------------------------------------------------

    painters = list(
        painters_map.values()
    )

    painters.sort(
        key=lambda p: p["name"].lower()
    )

    # ---------------------------------------------------------
    # 6. JSON
    # ---------------------------------------------------------

    output = {
        "source": (
            "French Wikipedia - "
            "Catégorie:Peintre français"
        ),
        "count": len(painters),
        "painters": painters
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    log(
        f"KÉSZ! Összesen {len(painters)} "
        f"francia festő adata elmentve ide: "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
