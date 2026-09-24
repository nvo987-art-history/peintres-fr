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


def save_json(painters_map):
    """
    Az eddig sikeresen letöltött és feldolgozott
    festők azonnali mentése.
    """

    if not painters_map:
        log("Nincs menthető adat.")
        return

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
        f"  -> MENTVE: {len(painters)} festő"
    )


def fetch_sparql_page(limit, offset, retries=5):
    """
    Egy SPARQL oldal lekérése.
    429 / 502 / 503 / 504 esetén újrapróbálkozik.
    """

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
                timeout=180,
                context=ssl_context
            ) as response:

                content = response.read().decode(
                    "utf-8",
                    errors="replace"
                )

                return json.loads(
                    content,
                    strict=False
                )

        except urllib.error.HTTPError as e:

            if e.code in (429, 502, 503, 504):

                retry_after = e.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        wait = 30
                else:
                    wait = min(
                        30 * attempt,
                        180
                    )

                log(
                    f"  [Újrapróbálkozás "
                    f"{attempt}/{retries}] "
                    f"HTTP {e.code}, "
                    f"várakozás {wait} mp..."
                )

                time.sleep(wait)
                continue

            log(
                f"  HTTP hiba: "
                f"{e.code} - {e.reason}"
            )

            return None

        except Exception as e:

            wait = min(
                30 * attempt,
                180
            )

            log(
                f"  [Újrapróbálkozás "
                f"{attempt}/{retries}] "
                f"Hiba: {e}"
            )

            log(
                f"  Várakozás {wait} mp..."
            )

            time.sleep(wait)

    return None


def main():

    log(
        "Francia festők adatainak "
        "lekérése Wikidatából..."
    )

    painters_map = {}

    # Egy oldal = 500 rekord
    limit = 500

    offset = 0
    page = 1

    while True:

        log(
            f"{page}. oldal lekérése "
            f"(OFFSET {offset}, "
            f"LIMIT {limit})..."
        )

        # ---------------------------------------------
        # 1. OLDAL LETÖLTÉSE
        # ---------------------------------------------

        res = fetch_sparql_page(
            limit,
            offset
        )

        if not res:

            log(
                "Ez az oldal nem tölthető le."
            )

            log(
                f"Az eddig letöltött "
                f"{len(painters_map)} "
                f"festő megmarad."
            )

            # Az eddigi adatok még egyszer
            # biztosan elmentve.
            save_json(painters_map)

            break

        bindings = (
            res
            .get("results", {})
            .get("bindings", [])
        )

        if not bindings:

            log(
                "Nincs több találat."
            )

            save_json(painters_map)

            break

        log(
            f"  -> {len(bindings)} "
            f"elem beérkezett."
        )

        # ---------------------------------------------
        # 2. AZ ÖSSZES BEÉRKEZETT REKORD FELDOLGOZÁSA
        # ---------------------------------------------

        for item in bindings:

            person_uri = (
                item
                .get("person", {})
                .get("value", "")
                .strip()
            )

            if not person_uri:
                continue

            qid = person_uri.rsplit(
                "/",
                1
            )[-1]

            if not qid.startswith("Q"):
                continue

            name = (
                item
                .get("name", {})
                .get("value", "")
                .strip()
            )

            wikipedia = (
                item
                .get("articleUrl", {})
                .get("value", "")
                .strip()
            )

            website = (
                item
                .get("websiteUrl", {})
                .get("value", "")
                .strip()
            )

            if not name or name == qid:
                continue

            painters_map[qid] = {
                "name": name,
                "wikidata": (
                    f"https://www.wikidata.org/wiki/{qid}"
                ),
                "wikipedia": wikipedia,
                "website": website
            }

        # ---------------------------------------------
        # 3. AZ OLDAL MENTÉSE AZONNAL
        # ---------------------------------------------

        save_json(painters_map)

        # ---------------------------------------------
        # 4. HA EZ VOLT AZ UTOLSÓ OLDAL
        # ---------------------------------------------

        if len(bindings) < limit:

            log(
                "Nincs több oldal."
            )

            break

        # ---------------------------------------------
        # 5. KÖVETKEZŐ OLDAL
        # ---------------------------------------------

        offset += limit
        page += 1

        log(
            "  -> Várakozás 5 mp..."
        )

        time.sleep(5)

    # ---------------------------------------------
    # VÉGSŐ ELLENŐRZÉS
    # ---------------------------------------------

    if painters_map:

        log(
            f"KÉSZ! Összesen "
            f"{len(painters_map)} "
            f"francia festő van a "
            f"painters.json fájlban."
        )

    else:

        raise RuntimeError(
            "Egyetlen festőt sem sikerült "
            "letölteni."
        )


if __name__ == "__main__":
    main()
