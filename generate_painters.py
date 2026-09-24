import json
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

# Q1028181 = painter (festő), Q142 = France (Franciaország)
PAINTER_TYPE = "wd:Q1028181"
FRANCE = "wd:Q142"

USER_AGENT = "Mozilla/5.0 (NVO987 Painters Bot; contact@example.com)"
MAX_WORKERS = 20  # Párhuzamos szálak a weboldalak ellenőrzéséhez

ssl_context = ssl.create_default_context()


def safe(value):
    return (value or "").strip()


def fetch_json(url_or_req, retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            req = url_or_req
            if isinstance(url_or_req, str):
                req = urllib.request.Request(url_or_req, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            last_error = error
            time.sleep(2 * (attempt + 1))
    raise last_error


def run_sparql(query):
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
    return fetch_json(req)


def fetch_wikipedia_links_batch(entity_ids):
    """Lekéri a francia és angol Wikipédia linkeket 50-es adagokban az API-n keresztül."""
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
        data = fetch_json(url)
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
        print(f"Hiba a Wikipédia API lekérdezésénél ({ids_str[:30]}...): {e}")
        return {}


def is_valid_website(url):
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        with urllib.request.urlopen(req, timeout=8, context=ssl_context) as response:
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
    # 1. LÉPÉS: Könnyű és gyors SPARQL lekérdezés (Wikipédia összekapcsolás nélkül)
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
        ?person wdt:P106 {PAINTER_TYPE} ;
                wdt:P27 {FRANCE} .

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
    """

    print("1/3: Francia festők alapadatainak lekérése a Wikidata-ról...")
    result = run_sparql(query)
    bindings = result.get("results", {}).get("bindings", [])

    raw_painters = []
    seen_ids = set()
    entity_ids = []

    for item in bindings:
        person_uri = safe(item.get("person", {}).get("value"))
        if not person_uri:
            continue

        person_id = person_uri.rsplit("/", 1)[-1]
        if person_id in seen_ids:
            continue
        seen_ids.add(person_id)

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

        painter = {
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
        raw_painters.append(painter)
        entity_ids.append(person_id)

    print(f"Beolvasva: {len(raw_painters)} festő.")

    # 2. LÉPÉS: Wikipédia linkek lekérése kötegekben (50 ID / kérés)
    print("2/3: Wikipédia hivatkozások lekérése API-n keresztül...")
    wiki_links = {}
    batch_size = 50
    for i in range(0, len(entity_ids), batch_size):
        batch = entity_ids[i:i + batch_size]
        links_batch = fetch_wikipedia_links_batch(batch)
        wiki_links.update(links_batch)

    # Wikipédia linkek hozzárendelése
    for painter in raw_painters:
        pid = painter["id"]
        if pid in wiki_links:
            painter["wikipedia_fr"] = wiki_links[pid]["wikipedia_fr"]
            painter["wikipedia_en"] = wiki_links[pid]["wikipedia_en"]

    # 3. LÉPÉS: Weboldalak párhuzamos ellenőrzése
    print(f"3/3: Saját weboldalak ellenőrzése párhuzamosan ({MAX_WORKERS} szálon)...")
    painters = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
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
