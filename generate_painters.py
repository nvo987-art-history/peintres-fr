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

PAGE_SIZE = 500


def log(msg):
    print(msg, flush=True)


def save_json(painters_map):
    """
    Az eddig sikeresen feldolgozott festők mentése.
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
                "  -> Nincs új változás."
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


def fetch_sparql_page(last_person_uri=None, retries=5):
    """
    500 Wikidata-személy lekérése.

    NINCS OFFSET.

    Az előző oldal utolsó QID-ja után folytatjuk.
    """

    if last_person_uri:

        pagination_filter = f"""
        FILTER(?person > <{last_person_uri}>)
        """

    else:

        pagination_filter = ""

    query = f"""
    SELECT ?person ?personLabel
    WHERE {{
        ?person wdt:P106 wd:Q1028181 ;
                wdt:P27 wd:Q142 ;
                wdt:P31 wd:Q5 .

        {pagination_filter}

        SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "fr,en" .
        }}
    }}

    ORDER BY ?person
    LIMIT {PAGE_SIZE}
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

            if e.code in (
                429,
                500,
                502,
                503,
                504
            ):

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


def fetch_details(qids, retries=5):
    """
    A már lekért QID-okhoz lekéri:
    - francia Wikipédia
    - hivatalos weboldal
    """

    if not qids:
        return {}

    values = " ".join(
        f"wd:{qid}"
        for qid in qids
    )

    query = f"""
    SELECT ?person ?article ?website
    WHERE {{
        VALUES ?person {{
            {values}
        }}

        OPTIONAL {{
            ?article schema:about ?person ;
                     schema:isPartOf <https://fr.wikipedia.org/> .
        }}

        OPTIONAL {{
            ?person wdt:P856 ?website .
        }}
    }}
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

                result = json.loads(
                    content,
                    strict=False
                )

                details = {}

                for item in (
                    result
                    .get("results", {})
                    .get("bindings", [])
                ):

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

                    if qid not in details:

                        details[qid] = {
                            "wikipedia": "",
                            "website": ""
                        }

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

                    if (
                        wikipedia
                        and not details[qid]["wikipedia"]
                    ):
                        details[qid]["wikipedia"] = wikipedia

                    if (
                        website
                        and not details[qid]["website"]
                    ):
                        details[qid]["website"] = website

                return details

        except urllib.error.HTTPError as e:

            if e.code in (
                429,
                500,
                502,
                503,
                504
            ):

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
                    f"  [Részletek újrapróbálkozás "
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

            return {}

        except Exception as e:

            wait = min(
                30 * attempt,
                180
            )

            log(
                f"  [Részletek újrapróbálkozás "
                f"{attempt}/{retries}] "
                f"Hiba: {e}"
            )

            time.sleep(wait)

    return {}


def main():

    log(
        "Francia festők adatainak "
        "lekérése Wikidatából..."
    )

    painters_map = {}

    last_person_uri = None

    page = 1

    # Az első 1000-es mérföldkő.
    next_commit_target = 1000

    while True:

        log(
            f"{page}. oldal lekérése "
            f"(500 rekord, "
            f"OFFSET NÉLKÜL)..."
        )

        # -----------------------------------------
        # 1. FESTŐK LEKÉRÉSE
        # -----------------------------------------

        res = fetch_sparql_page(
            last_person_uri
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

            # JSON mentés
            save_json(painters_map)

            # Hiba esetén mindig pusholjuk
            # az addig elkészült állapotot.
            if painters_map:

                git_commit_and_push(
                    len(painters_map)
                )

            # A workflow hibásan fejezhető be,
            # de az adatok már GitHubon vannak.
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

            if painters_map:

                git_commit_and_push(
                    len(painters_map)
                )

            break

        log(
            f"  -> {len(bindings)} "
            f"festő érkezett."
        )

        # -----------------------------------------
        # 2. ALAPADATOK FELDOLGOZÁSA
        # -----------------------------------------

        page_qids = []

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

            if not name or name == qid:
                continue

            painters_map[qid] = {
                "name": name,
                "wikidata": (
                    f"https://www.wikidata.org/wiki/{qid}"
                ),
                "wikipedia": "",
                "website": ""
            }

            page_qids.append(qid)

            # Ez lesz a következő oldal kezdőpontja.
            last_person_uri = person_uri

        # -----------------------------------------
        # 3. WIKIPÉDIA + WEBSITE
        # -----------------------------------------

        details = fetch_details(
            page_qids
        )

        for qid, data in details.items():

            if qid not in painters_map:
                continue

            painters_map[qid]["wikipedia"] = (
                data.get("wikipedia", "")
            )

            painters_map[qid]["website"] = (
                data.get("website", "")
            )

        # -----------------------------------------
        # 4. AZONNALI JSON MENTÉS
        # -----------------------------------------

        current_count = len(
            painters_map
        )

        log(
            f"  -> Feldolgozva: "
            f"{current_count} festő"
        )

        save_json(
            painters_map
        )

        # -----------------------------------------
        # 5. 1000-ES MÉRFÖLDKŐ
        # -----------------------------------------

        if current_count >= next_commit_target:

            git_commit_and_push(
                current_count
            )

            # Következő mérföldkő:
            # 2000, 3000, 4000...
            while (
                next_commit_target
                <= current_count
            ):
                next_commit_target += 1000

        # -----------------------------------------
        # 6. UTOLSÓ OLDAL?
        # -----------------------------------------

        if len(bindings) < PAGE_SIZE:

            log(
                "Nincs több oldal."
            )

            # A végén mindig legyen push.
            if painters_map:

                git_commit_and_push(
                    current_count
                )

            break

        # -----------------------------------------
        # 7. KÖVETKEZŐ OLDAL
        # -----------------------------------------

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
