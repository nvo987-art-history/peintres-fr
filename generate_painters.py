import json
import ssl
import time
import urllib.parse
import urllib.request

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

# Egyedi User-Agent a Wikidata szabályzatának megfelelően
USER_AGENT = "PeintresFrBot/1.0 (https://github.com/nvo987-art-history/peintres-fr; contact@example.com)"
ssl_context = ssl.create_default_context()


def log(msg):
    """Azonnali konzolra írás GitHub Actions-ben."""
    print(msg, flush=True)


def safe(value):
    return (value or "").strip()


def fetch_json(url_or_req, timeout=30, retries=5):
    """JSON lekérése automatikus újrapróbálkozással 429 / hálózati hiba esetén."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = url_or_req
            if isinstance(url_or_req, str):
                req = urllib.request.Request(url_or_req, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
                content = response.read().decode("utf-8", errors="replace")
                return json.loads(content, strict=False)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429:
                log(f"  [429 Too Many Requests] Várakozás {6 * attempt} másodpercet...")
                time.sleep(6 * attempt)
            else:
                time.sleep(3 * attempt)
        except Exception as error:
            last_error = error
            time.sleep(3 * attempt)
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
    log("1/3: Francia festők azonosítóinak (QID) lekérése...")
    res = run_sparql(query, timeout=60)
    bindings = res.get("results", {}).get("bindings", [])

    qids = []
    for item in bindings:
        uri = safe(item.get("person", {}).get("value"))
        if uri:
            qid = uri.rsplit("/", 1)[-1]
            if qid.startswith("Q"):
                qids.append(qid)

    log(f"Megtalálva: {len(qids)} festő azonosító.")
    return qids


def fetch_batch_details(qids_chunk):
    """2. LÉPÉS: Részletes adatok lekérése 50 festőre egyszerre."""
    values_str = " ".join([f"wd:{qid}" for qid in qids_chunk])
    query = f"""
    SELECT DISTINCT ?person ?personLabel ?description ?website ?birthDate ?deathDate ?birthPlaceLabel ?coord WHERE {{
        VALUES ?person {{ {values_str} }}

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
    return run_sparql(query, timeout=30)


def fetch_wikipedia_links_batch(qids_chunk):
    """Wikipédia linkek lekérése a Wikidata API-ból."""
    ids_str = "|".join(qids_chunk)
    params = urllib.parse.urlencode({
        "action": "wbgetentities",
        "ids": ids_str,
        "props": "sitelinks",
        "sitefilter": "frwiki|enwiki",
        "format": "json"
    })
    url = f"{WIKIDATA_API_URL}?{params}"
    try:
        data = fetch_json(url, timeout=20, retries=3)
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
    qids = get_all_painter_ids()
    if not qids:
        log("Nem sikerült azonosítókat lekérni.")
        return

    raw_painters_map = {}
    batch_size = 50
    total_batches = (len(qids) + batch_size - 1) // batch_size

    log(f"2/3: Részletes adatok és Wikipédia linkek lekérése {batch_size}-es csomagokban...")

    for i in range(0, len(qids), batch_size):
        chunk = qids[i:i + batch_size]
        current_batch = (i // batch_size) + 1

        if current_batch % 20 == 0 or current_batch == total_batches:
            log(f"  Feldolgozás: {current_batch}/{total_batches} csomag ({len(raw_painters_map)} festő beolvasva)...")

        # SPARQL adatok
        try:
            res = fetch_batch_details(chunk)
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
                    "website_valid": bool(website),
                    "wikipedia_fr": "",
                    "wikipedia_en": "",
                    "description": description,
                    "source": f"https://www.wikidata.org/wiki/{person_id}"
                }
        except Exception as e:
            log(f"  [Hiba a(z) {current_batch}. csomagnál]: {e}")

        # Wikipédia linkek
        wiki_links = fetch_wikipedia_links_batch(chunk)
        for pid, links in wiki_links.items():
            if pid in raw_painters_map:
                raw_painters_map[pid]["wikipedia_fr"] = links["wikipedia_fr"]
                raw_painters_map[pid]["wikipedia_en"] = links["wikipedia_en"]

        # KÉRÉSEK KÖZÖTTI SZÜNET: Így nem kapunk 429-es Letiltást a Wikidatától!
        time.sleep(0.3)

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
