import json
import ssl
import time
import urllib.parse
import urllib.request

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "FrenchPaintersBot/1.0 (https://github.com/nvo987-art-history/peintres-fr; contact@example.com)"
ssl_context = ssl.create_default_context()


def log(msg):
    """Azonnali konzolra írás GitHub Actions-ben."""
    print(msg, flush=True)


def fetch_sparql_page(limit, offset, retries=3):
    """Francia festők lekérése a francia Wikipédia kategóriájából."""
    query = f"""
    SELECT DISTINCT ?person ?personLabel ?article ?website WHERE {{
      SERVICE wikibase:mwapi {{
        bd:serviceParam
          wikibase:endpoint "fr.wikipedia.org";
          wikibase:api "Generator";
          mwapi:generator "categorymembers";
          mwapi:gcmtitle "Catégorie:Peintre français";
          mwapi:gcmtype "page";
          mwapi:gcmnamespace "0";
          mwapi:gcmlimit "max".

        ?article wikibase:apiOutput mwapi:title .
      }}

      ?article schema:about ?person ;
               schema:isPartOf <https://fr.wikipedia.org/> .

      OPTIONAL {{
        ?person wdt:P856 ?website .
      }}

      SERVICE wikibase:label {{
        bd:serviceParam wikibase:language "fr,en" .
      }}
    }}
    LIMIT {limit}
    OFFSET {offset}
    """

    data = urllib.parse.urlencode(
        {"query": query, "format": "json"}
    ).encode("utf-8")

    req = urllib.request.Request(
        SPARQL_URL,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        method="POST"
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
                f"  [Újrapróbálkozás {attempt}/{retries}] Hiba: {e}"
            )
            time.sleep(4 * attempt)

    return None


def main():
    log("Francia festők adatainak lekérése...")
    painters_map = {}

    limit = 5000
    offset = 0
    page = 1

    while True:
        log(
            f"{page}. oldal lekérése "
            f"(OFFSET {offset}, LIMIT {limit})..."
        )

        res = fetch_sparql_page(limit, offset)

        if not res:
            log("Nem érkezett válasz, leállítás.")
            break

        bindings = res.get(
            "results",
            {}
        ).get(
            "bindings",
            []
        )

        if not bindings:
            log("Nincs több találat.")
            break

        log(f"  -> {len(bindings)} elem beérkezett.")

        for item in bindings:
            person_uri = item.get(
                "person",
                {}
            ).get(
                "value",
                ""
            ).strip()

            if not person_uri:
                continue

            qid = person_uri.rsplit("/", 1)[-1]

            if not qid.startswith("Q"):
                continue

            name = item.get(
                "personLabel",
                {}
            ).get(
                "value",
                ""
            ).strip()

            wikipedia = item.get(
                "article",
                {}
            ).get(
                "value",
                ""
            ).strip()

            website = item.get(
                "website",
                {}
            ).get(
                "value",
                ""
            ).strip()

            if qid not in painters_map:
                painters_map[qid] = {
                    "name": name if name != qid else "",
                    "wikidata": f"https://www.wikidata.org/wiki/{qid}",
                    "wikipedia": wikipedia,
                    "website": website
                }

            else:
                if wikipedia and not painters_map[qid]["wikipedia"]:
                    painters_map[qid]["wikipedia"] = wikipedia

                if website and not painters_map[qid]["website"]:
                    painters_map[qid]["website"] = website

        if len(bindings) < limit:
            break

        offset += limit
        page += 1
        time.sleep(2)

    painters = list(painters_map.values())

    painters.sort(
        key=lambda p: p["name"].lower()
    )

    output = {
        "source": "French Wikipedia - Catégorie:Peintre français",
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
        f"francia festő adata elmentve ide: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
