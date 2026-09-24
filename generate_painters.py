import json
import ssl
import time
import subprocess
import urllib.parse
import urllib.request
import urllib.error

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "FrenchPaintersBot/1.0 (https://github.com/nvo987-art-history/peintres-fr)"

ssl_context = ssl.create_default_context()


def log(msg):
    print(msg, flush=True)


def execute_sparql(query, retries=5):
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
            with urllib.request.urlopen(req, timeout=60, context=ssl_context) as response:
                content = response.read().decode("utf-8", errors="replace")
                return json.loads(content, strict=False)

        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(15 * attempt, 90)
                log(f"  [Újrapróbálkozás {attempt}/{retries}] HTTP {e.code}, várakozás {wait} mp...")
                time.sleep(wait)
            else:
                log(f"  HTTP hiba: {e.code} - {e.reason}")
                return None
        except Exception as e:
            wait = min(15 * attempt, 90)
            log(f"  [Újrapróbálkozás {attempt}/{retries}] Hiba: {e}, várakozás {wait} mp...")
            time.sleep(wait)

    return None


def fetch_all_painter_qids():
    """1. LÉPÉS: QID-k lekérése egyetlen gyors lekérdezéssel."""
    log("Francia festők QID azonosítóinak lekérése...")
    query = """
    SELECT DISTINCT ?person WHERE {
      ?person wdt:P106 wd:Q1028181 ;
              wdt:P27 wd:Q142 ;
              wdt:P31 wd:Q5 .
    }
    """
    res = execute_sparql(query)
    if not res:
        return []

    bindings = res.get("results", {}).get("bindings", [])
    qids = []
    for item in bindings:
        uri = item.get("person", {}).get("value", "")
        qid = uri.rsplit("/", 1)[-1]
        if qid.startswith("Q"):
            qids.append(qid)

    log(f"  -> Összesen {len(qids)} festő azonosítója megtalálva.")
    return qids


def fetch_details_for_batch(qid_chunk):
    """2. LÉPÉS: Részletek lekérése 200 elemes kötegekben (VALUES használatával)."""
    values_str = " ".join([f"wd:{qid}" for qid in qid_chunk])

    query = f"""
    SELECT ?person ?personLabel ?article ?website WHERE {{
      VALUES ?person {{ {values_str} }}

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
    """
    return execute_sparql(query)


def save_json(painters_map):
    painters = sorted(list(painters_map.values()), key=lambda p: p["name"].lower())
    output = {
        "source": "Wikidata (CC0)",
        "count": len(painters),
        "painters": painters
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def git_commit_and_push(count):
    log(f"  -> Git commit + push indítása ({count} festő)...")
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", OUTPUT_FILE], check=True)

        status = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if status.returncode == 0:
            log("  -> Nincs új változás, commit nem szükséges.")
            return True

        subprocess.run(["git", "commit", "-m", f"weekly: update painters data ({count})"], check=True)
        subprocess.run(["git", "push"], check=True)
        log(f"  -> PUSH KÉSZ: {count} festő adata feltöltve.")
        return True
    except subprocess.CalledProcessError as e:
        log(f"  -> Git hiba: {e}")
        return False


def main():
    painters_map = {}
    has_error = False

    try:
        # 1. QID-k lekérése
        qids = fetch_all_painter_qids()
        if not qids:
            has_error = True
            raise RuntimeError("Nem sikerült lekérni a QID azonosítókat.")

        # 2. Kötegelt adatletöltés
        batch_size = 200
        total_batches = (len(qids) + batch_size - 1) // batch_size

        for i in range(0, len(qids), batch_size):
            chunk = qids[i:i + batch_size]
            current_batch = (i // batch_size) + 1

            log(f"Köteg {current_batch}/{total_batches} lekérése...")
            res = fetch_details_for_batch(chunk)

            if not res:
                log(f"  [HIBA] A {current_batch}. köteg letöltése meghiúsult.")
                has_error = True
                continue

            bindings = res.get("results", {}).get("bindings", [])

            for item in bindings:
                person_uri = item.get("person", {}).get("value", "").strip()
                qid = person_uri.rsplit("/", 1)[-1]
                name = item.get("personLabel", {}).get("value", "").strip()
                wikipedia = item.get("article", {}).get("value", "").strip()
                website = item.get("website", {}).get("value", "").strip()

                if not name or name == qid:
                    continue

                if qid not in painters_map:
                    painters_map[qid] = {
                        "name": name,
                        "wikidata": f"https://www.wikidata.org/wiki/{qid}",
                        "wikipedia": wikipedia,
                        "website": website
                    }
                else:
                    if wikipedia and not painters_map[qid]["wikipedia"]:
                        painters_map[qid]["wikipedia"] = wikipedia
                    if website and not painters_map[qid]["website"]:
                        painters_map[qid]["website"] = website

            time.sleep(1)

    except Exception as e:
        log(f"Váratlan hiba történt a futás során: {e}")
        has_error = True

    finally:
        # Ez a blokk MINDIG lefut (sikeres futásnál és összeomlásnál is)
        if painters_map:
            log("-> Részleges/Teljes adatok mentése és PUSH-olása a GitHubra...")
            save_json(painters_map)
            git_commit_and_push(len(painters_map))
        else:
            log("-> Nincs menthető adat.")

        # Ha hiba történt, dobot egy RuntimeError-t a legvégén,
        # így a GitHub Actions PIROS lesz, de az adatok MÁR BENT VANNAK a repo-ban!
        if has_error:
            raise RuntimeError("A folyamat nem fejeződött be 100%-osan, de a részleges adatok mentve lettek.")


if __name__ == "__main__":
    main()
