import json
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

USER_AGENT = "PeintresFrBot/1.0 (https://github.com/peintres-fr/peintres-fr; contact@example.com)"
ssl_context = ssl.create_default_context()


def safe(value):
    return (value or "").strip()


def fetch_json(url_or_req, timeout=30, retries=3):
    """JSON lekérése érvényesítéssel és hibatűréssel."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = url_or_req
            if isinstance(url_or_req, str):
                req = urllib.request.Request(url_or_req, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
                content = response.read().decode("utf-8", errors="replace")
                # strict=False segít a vezérlőkarakterek kezelésében
                return json.loads(content, strict=False)
        except Exception as error:
            last_error = error
            time.sleep(2 * attempt)
    raise last_error


def run_sparql(query, timeout=40):
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode("utf-8")
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
    return fetch_json(req, timeout=timeout)


def get_all_painter_ids():
    """1. LÉPÉS: Csak a QID azonosítók lekérése (villámgyors, ~1 mp)."""
    query = """
    SELECT DISTINCT ?person WHERE {
        ?person wdt:P106 wd:Q1028181 ;
                wdt:P27 wd:Q142 .
    }
    """
    print("1/4: Az összes francia festő azonosítójának (QID) lekérése...")
    result = run_sparql(query, timeout=60)
    bindings = result.get("results", {}).get("bindings", [])

    qids = []
    for item in bindings:
        uri = safe(item.get("person", {}).get("value"))
        if uri:
            qid = uri.rsplit("/", 1)[-1]
            if qid.startswith("Q"):
                qids.append(qid)
    print(f"Megtalálva: {len(qids)} festő azonosító.")
    return qids


def fetch_batch_metadata(qid_batch):
    """2. LÉPÉS: Részletes adatok lekérése egy 200-as ID csomagra."""
    values_clause = " ".join([f"wd:{qid}" for qid in qid_batch])
    query = f"""
    SELECT DISTINCT ?person ?personLabel ?description ?website ?birthDate ?deathDate ?birthPlaceLabel ?coord WHERE {{
        VALUES ?person {{ {values_clause} }}

        OPTIONAL {{ ?person wdt:P856 ?website . }}
        OPTIONAL {{ ?person wdt:P569 ?birthDate . }}
        OPTIONAL {{ ?person wdt:P570 ?deathDate . }}
        OPTIONAL {{ ?person wdt:P19 ?birthPlace . }}
        OPTIONAL {{ ?person wdt:P625 ?coord . }}
        OPTIONAL {{
            ?person schema:description ?description .
            FILTER(LANG(?description) = "fr")
        }}
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en" . }}
    }}
    """
    return run_sparql(query, timeout=40)


def fetch_wikipedia_links_batch(entity_ids):
    """3. LÉPÉS: Wikipédia linkek lekérése a Wikidata API-n keresztül."""
    if not entity_ids:
        return {}

    ids_str = "|".join(entity_ids)
    params = urllib.parse.urlencode({
        "action": "wbgetentities",
        "ids": ids_str,
        "props": "sitelinks",
        "sitefilter": "frwiki|enwiki",
        "format": "json"
    })

    url = f"{WIKIDATA_API_URL}?{params}"
    try:
        data = fetch_json(url, timeout=30, retries=3)
        entities = data.get("entities", {})

        links = {}
        for qid, entity_data in entities.items():
            sitelinks = entity_data.get("sitelinks", {})

            fr_title = sitelinks.get("frwiki", {}).get("title")
            en_title = sitelinks.get("enwiki", {}).get("title")

            links[qid] = {
                "wikipedia_fr": f"https://fr.wikipedia.org/wiki/{urllib.parse.quote(fr_title.replace(' ', '_'))}" if fr_title else "",
                "wikipedia_en": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(en_title.replace(' ', '_'))}" if en_title else ""
            }
        return links
    except Exception as e:
        print(f"Hiba a Wikipédia API lekérdezésénél: {e}")
        return {}


def is_valid_website(url):
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
            return response.status < 400
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
            with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
                return response.status < 400
        except Exception:
            return False


def check_painter_website(painter):
    if painter["website"]:
        painter["website_valid"] = is_valid_website(painter["website"])
    return painter


def main():
    # 1. Lekérjük az azonosítókat
    qids = get_all_painter_ids()
    if not qids:
        print("Nem található egyetlen azonosító sem.")
        return

    # 2. Adatok lekérése 200-as kötegekben
    print("2/4: Részletes adatok lekérése 200-as kötegekben (batching)...")
    raw_painters_map = {}
    batch_size = 200
    total_batches = (len(qids) + batch_size - 1) // batch_size

    for i in range(0, len(qids), batch_size):
        chunk_qids = qids[i:i + batch_size]
        current_batch = (i // batch_size) + 1
        print(f"  Köteg feldolgozása: {current_batch}/{total_batches} ({len(chunk_qids)} festő)...")

        try:
            res = fetch_batch_metadata(chunk_qids)
            bindings = res.get("results", {}).get("bindings", [])

            for item in bindings:
                person_uri = safe(item.get("person", {}).get("value"))
                if not person_uri:
                    continue

                person_id = person_uri.rsplit("/", 1)[-1]
                if person_id in raw_painters_map:
                    continue

                name = safe(item.get("personLabel", {}).get("value"))
                if not name:
                    continue

                description = safe(item.get("description", {}).get("value"))
                website = safe(item.get("website", {}).get("value"))
                birth_date = safe(item.get("birthDate", {}).get("value"))
                death_date = safe(item.get("deathDate", {}).get("value"))
                birth_place = safe(item.get("birthPlaceLabel", {}).get("value"))
                coord = safe(item.get("coord", {}).get("value"))

                lat, lon = None, None
                if coord.startswith("Point(") and coord.endswith(")"):
                    try:
                        values = coord[6:-1].split()
                        lon = float(values[0])
                        lat = float(values[1])
                    except (ValueError, IndexError):
                        pass

                raw_painters_map[person_id] = {
                    "id": person_id,
                    "name": name,
                    "type": "French painter",
                    "birth": birth_date[:10] if birth_date else "",
                    "death": death_date[:10] if death_date else "",
                    "birthPlace": birth_place,
                    "lat": lat,
                    "lon": lon,
                    "website": website,
                    "website_valid": False,
                    "wikipedia_fr": "",
                    "wikipedia_en": "",
                    "description": description,
                    "source": f"https://www.wikidata.org/wiki/{person_id}"
                }
        except Exception as e:
            print(f"  [Figyelmeztetés a(z) {current_batch}. kötegnél]: {e}. Folytatás a következővel...")

    raw_painters = list(raw_painters_map.values())
    entity_ids = list(raw_painters_map.keys())
    print(f"Összesen {len(raw_painters)} festő adatai sikeresen beolvasva.")

    # 3. Wikipédia linkek
    print("3/4: Wikipédia hivatkozások lekérése API-n keresztül...")
    wiki_links = {}
    wiki_batch_size = 50
    for i in range(0, len(entity_ids), wiki_batch_size):
        batch = entity_ids[i:i + wiki_batch_size]
        links_batch = fetch_wikipedia_links_batch(batch)
        wiki_links.update(links_batch)

    for painter in raw_painters:
        pid = painter["id"]
        if pid in wiki_links:
            painter["wikipedia_fr"] = wiki_links[pid]["wikipedia_fr"]
            painter["wikipedia_en"] = wiki_links[pid]["wikipedia_en"]

    # 4. Weboldalak ellenőrzése
    print("4/4: Saját weboldalak ellenőrzése párhuzamosan (10 szálon)...")
    painters = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_painter_website, p) for p in raw_painters]
        for future in as_completed(futures):
            painters.append(future.result())

    painters.sort(key=lambda p: p["name"].lower())

    output = {
        "source": "Wikidata (CC0)",
        "license": "CC0 1.0",
        "country": "France",
        "type": "French painters",
        "count": len(painters),
        "painters": painters
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(f"Sikeres futás: {len(painters)} festő elmentve ide: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
