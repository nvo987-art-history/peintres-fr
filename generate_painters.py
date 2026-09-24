import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

USER_AGENT = "PeintresFrBot/1.0 (https://github.com/nvo987-art-history/peintres-fr; contact@example.com)"
ssl_context = ssl.create_default_context()


def log(msg):
    """Azonnali kiírás a konzolra (flush=True), hogy a GitHub Actions-ben rögtön látszódjon."""
    print(msg, flush=True)


def safe(value):
    return (value or "").strip()


def fetch_json(url_or_req, timeout=30, retries=3):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = url_or_req
            if isinstance(url_or_req, str):
                req = urllib.request.Request(url_or_req, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
                content = response.read().decode("utf-8", errors="replace")
                return json.loads(content, strict=False)
        except Exception as error:
            last_error = error
            time.sleep(2 * attempt)
    raise last_error


def run_sparql_page(limit=1000, offset=0):
    query = f"""
    SELECT DISTINCT
        ?person
        ?personLabel
        ?description
        ?website
        ?birthDate
        ?deathDate
        ?birthPlaceLabel
        ?coord
    WHERE {{
        ?person wdt:P106 wd:Q1028181 ;
                wdt:P27 wd:Q142 .

        OPTIONAL {{ ?person wdt:P856 ?website . }}
        OPTIONAL {{ ?person wdt:P569 ?birthDate . }}
        OPTIONAL {{ ?person wdt:P570 ?deathDate . }}
        OPTIONAL {{ ?person wdt:P19 ?birthPlace . }}
        OPTIONAL {{ ?person wdt:P625 ?coord . }}

        OPTIONAL {{
            ?person schema:description ?description .
            FILTER(LANG(?description) = "fr")
        }}

        SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "fr,en" .
        }}
    }}
    LIMIT {limit} OFFSET {offset}
    """
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
    return fetch_json(req, timeout=40)


def fetch_wikipedia_links_batch(entity_ids):
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
        data = fetch_json(url, timeout=20, retries=2)
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
    except Exception:
        return {}


def main():
    log("1/3: Francia festők adatainak lekérése a Wikidatáról lapozással...")

    raw_painters_map = {}
    limit = 1000
    offset = 0

    while True:
        log(f"  Oldal lekérése: OFFSET {offset} (LIMIT {limit})...")
        try:
            res = run_sparql_page(limit=limit, offset=offset)
            bindings = res.get("results", {}).get("bindings", [])

            if not bindings:
                log("  Nincs több adat.")
                break

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
                    "website_valid": bool(website),
                    "wikipedia_fr": "",
                    "wikipedia_en": "",
                    "description": description,
                    "source": f"https://www.wikidata.org/wiki/{person_id}"
                }

            log(f"  Eddig beolvasva: {len(raw_painters_map)} egyedi festő.")
            if len(bindings) < limit:
                break

            offset += limit

        except Exception as e:
            log(f"  [Hiba az OFFSET {offset} lapnál]: {e}. Újrapróbálkozás...")
            offset += limit

    entity_ids = list(raw_painters_map.keys())
    log(f"Összesen {len(entity_ids)} festő alapadatai sikeresen beolvasva.")

    log("2/3: Wikipédia hivatkozások lekérése az API-ból párhuzamosan...")
    wiki_batch_size = 50
    batches = [entity_ids[i:i + wiki_batch_size] for i in range(0, len(entity_ids), wiki_batch_size)]

    wiki_links = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_batch = {executor.submit(fetch_wikipedia_links_batch, b): b for b in batches}
        for future in as_completed(future_to_batch):
            res = future.result()
            wiki_links.update(res)

    for pid, painter in raw_painters_map.items():
        if pid in wiki_links:
            painter["wikipedia_fr"] = wiki_links[pid]["wikipedia_fr"]
            painter["wikipedia_en"] = wiki_links[pid]["wikipedia_en"]

    log("3/3: Adatok rendezése és mentése...")
    painters = list(raw_painters_map.values())
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

    log(f"KÉSZ! {len(painters)} festő adatai elmentve ide: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
