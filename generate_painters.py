import json
import ssl
import time
import subprocess
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


def git_commit_and_push(count):
    """
    Git commit + push.
    Ezt minden 2 sikeres oldal, kb. 1000 festő után
    meghívjuk.
    """

    log(
        f"  -> Git commit + push "
        f"({count} festő)..."
    )

    try:

        subprocess.run(
            [
                "git",
                "config",
                "--global",
                "user.name",
                "github-actions[bot]"
            ],
            check=True
        )

        subprocess.run(
            [
                "git",
                "config",
                "--global",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com"
            ],
            check=True
        )

        subprocess.run(
            ["git", "add", OUTPUT_FILE],
            check=True
        )

        # Megnézzük, van-e tényleges változás.
        status = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet"
            ]
        )

        if status.returncode == 0:
            log(
                "  -> Nincs új változás, "
                "commit nem szükséges."
            )
            return True

        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"weekly: update painters data ({count})"
            ],
            check=True
        )

        subprocess.run(
            ["git", "push"],
            check=True
        )

        log(
            f"  -> PUSH KÉSZ: {count} festő"
        )

        return True

    except subprocess.CalledProcessError as e:

        log(
            f"  -> Git hiba: {e}"
        )

        return False


def fetch_sparql_page(limit, offset, retries=5):
    """
    Egy SPARQL oldal lekérése.

    429 / 502 / 503 / 504 esetén
    újrapróbálkozik.
    """

    query = f"""
    SELECT ?person ?personLabel ?article ?website WHERE {{
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

    # Minden második oldal után commit + push.
    # 500 + 500 = kb. 1000 rekord.
    #
    # FONTOS:
    # Ez NEM maximális rekordszám.
    # Csak azt szabályozza, milyen gyakran
    # készül commit + push.
    pages_since_commit = 0

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

        # ---------------------------------------------
        # HA HIBA TÖRTÉNIK
        # ---------------------------------------------

        if not res:

            log(
                "Ez az oldal nem tölthető le."
            )

            log(
                f"Az eddig letöltött "
                f"{len(painters_map)} "
                f"festő megmarad."
            )

            # Először JSON mentés
            save_json(painters_map)

            # Majd az eddigiek AZONNALI commit + push
            if painters_map:
                git_commit_and_push(
                    len(painters_map)
                )

            # FONTOS:
            # NEM break!
            #
            # A break miatt a Python sikeresen
            # befejeződött volna, ezért a GitHub
            # Actions zöld lett.
            #
            # A raise miatt a workflow PIROS lesz,
            # miközben az addig letöltött adatok
            # már GitHubon vannak.
            raise RuntimeError(
                f"A Wikidata lekérdezés sikertelen: "
                f"{page}. oldal, "
                f"OFFSET {offset}"
            )

        bindings = (
            res
            .get("results", {})
            .get("bindings", [])
        )

        # ---------------------------------------------
        # NINCS TÖBB TALÁLAT
        # ---------------------------------------------

        if not bindings:

            log(
                "Nincs több találat."
            )

            save_json(painters_map)

            if painters_map:
                git_commit_and_push(
                    len(painters_map)
                )

            break

        log(
            f"  -> {len(bindings)} "
            f"elem beérkezett."
        )

        # ---------------------------------------------
        # 2. REKORDOK FELDOLGOZÁSA
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
                .get("personLabel", {})
                .get("value", "")
                .strip()
            )

            wikipedia = (
                item
                .get("article", {})
                .get("value", "")
                .strip()
            )

            website = (
                item
                .get("website", {})
                .get("value", "")
                .strip()
            )

            if not name or name == qid:
                continue

            # -----------------------------------------
            # ÚJ FESTŐ
            # -----------------------------------------

            if qid not in painters_map:

                painters_map[qid] = {
                    "name": name,
                    "wikidata": (
                        f"https://www.wikidata.org/wiki/{qid}"
                    ),
                    "wikipedia": wikipedia,
                    "website": website
                }

            # -----------------------------------------
            # HIÁNYZÓ ADATOK PÓTLÁSA
            # -----------------------------------------

            else:

                if (
                    wikipedia
                    and not painters_map[qid]["wikipedia"]
                ):
                    painters_map[qid]["wikipedia"] = wikipedia

                if (
                    website
                    and not painters_map[qid]["website"]
                ):
                    painters_map[qid]["website"] = website

        # ---------------------------------------------
        # 3. AZONNALI JSON MENTÉS
        # ---------------------------------------------

        log(
            f"  -> Feldolgozva: "
            f"{len(painters_map)} festő"
        )

        save_json(painters_map)

        pages_since_commit += 1

        # ---------------------------------------------
        # 4. MINDEN 2. OLDAL = COMMIT + PUSH
        # ---------------------------------------------

        if pages_since_commit >= 2:

            git_commit_and_push(
                len(painters_map)
            )

            pages_since_commit = 0

        # ---------------------------------------------
        # 5. UTOLSÓ OLDAL?
        # ---------------------------------------------

        if len(bindings) < limit:

            log(
                "Nincs több oldal."
            )

            # Ha maradt egy nem commitolt oldal,
            # azt is pusholjuk.
            if pages_since_commit > 0:

                git_commit_and_push(
                    len(painters_map)
                )

                pages_since_commit = 0

            break

        # ---------------------------------------------
        # 6. KÖVETKEZŐ OLDAL
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
            f"francia festő mentve."
        )

    else:

        raise RuntimeError(
            "Egyetlen festőt sem sikerült "
            "letölteni."
        )


if __name__ == "__main__":
    main()
