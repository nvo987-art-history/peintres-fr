import json
import ssl
import time
import urllib.parse
import urllib.request
import urllib.error

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"

USER_AGENT = (
    "FrenchPaintersBot/1.0 "
    "(https://github.com/nvo987-art-history/peintres-fr)"
)

ssl_context = ssl.create_default_context()


def log(msg):
    print(msg, flush=True)


def fetch_sparql_page(limit, offset, retries=5):
    query = f"""
    SELECT
      ?person
      (SAMPLE(?personLabel) AS ?name)
      (SAMPLE(?article) AS ?articleUrl)
      (SAMPLE(?website) AS ?websiteUrl)
    WHERE {{
      ?person wdt:P106 wd:Q1028181 ;
              wdt:P27 wd:Q142 ;
              wdt:P31 wd:Q5 .

      OPTIONAL {{
        ?article schema:about ?person ;
                 schema:isPartOf <https://fr.wikipedia.org/> .
      }}

      OPTIONAL {{
        ?person wdt:P856 ?website .
      }}

      SERVICE wikibase:label {{
        bd:serviceParam wikibase:language "fr,en" .
      }}
    }}
    GROUP BY ?person
    ORDER BY ?person
    LIMIT {limit}
    OFFSET {offset}
    """

    data = urllib.parse.urlencode({
        "query": query,
        "format": "json"
    }).encode("utf-8")

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
                timeout=120,
                context=ssl_context
            ) as response:
                content = response.read().decode(
                    "utf-8",
                    errors="replace"
                )
                return json.loads(content, strict=False)

        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                retry_after = e.headers.get("Retry-After")

                if retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        wait = 15
                else:
                    wait = 10 * attempt

                log(
                    f"  [Újrapróbálkozás {attempt}/{retries}] "
                    f"HTTP {e.code}, várakozás {wait} mp..."
                )

                time.sleep(wait)
                continue

            log(f"  HTTP hiba: {e.code} - {e.reason}")
            return None

        except Exception as e:
            log(
                f"  [Újrapróbálkozás {attempt}/{retries}] "
                f"Hiba: {e}"
            )
            time.sleep(5 * attempt)

    return None


def main():
    log("Francia festők adatainak lekérése Wikidatából...")

    painters_map = {}

    # Kisebb oldalak, hogy ne legyen túl nehéz a SPARQL lekérdezés.
    limit = 500
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

        bindings = res.get("results", {}).get("bindings", [])

        if not bindings:
            log("Nincs több találat.")
            break

        log(f"  -> {len(bindings)} elem beérkezett.")

        for item in bindings:

            person_uri = (
                item.get("person", {})
                .get("value", "")
                .strip()
            )

            if not person_uri:
                continue

            qid = person_uri.rsplit("/", 1)[-1]

            if not qid.startswith("Q"):
                continue

            name = (
                item.get("name", {})
                .get("value", "")
                .strip()
            )

            wikipedia = (
                item.get("articleUrl", {})
                .get("value", "")
                .strip()
            )

            website = (
                item.get("websiteUrl", {})
                .get("value", "")
                .strip()
            )

            if not name or name == qid:
                continue

            painters_map[qid] = {
                "name": name,
                "wikidata": f"https://www.wikidata.org/wiki/{qid}",
                "wikipedia": wikipedia,
                "website": website
            }

        if len(bindings) < limit:
            break

        offset += limit
        page += 1

        # Ne küldjük folyamatosan a lekéréseket.
        time.sleep(3)

    painters = list(painters_map.values())

    painters.sort(
        key=lambda p: p["name"].lower()
    )

    output = {
        "source": "Wikidata (CC0)",
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
        f"francia festő elmentve: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
