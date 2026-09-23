# generate_painters.py

import json
import time
import urllib.parse
import urllib.request
import ssl

OUTPUT_FILE = "painters.json"
SPARQL_URL = "https://query.wikidata.org/sparql"

PAINTER_TYPE = "wd:Q49757"  # painter
FRANCE = "wd:Q142"

USER_AGENT = "Mozilla/5.0 (NVO987 Painters Bot)"

ssl_context = ssl.create_default_context()


def safe(value):
    return (value or "").strip()


def is_valid_website(url):
    if not url:
        return False

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT
            },
            method="HEAD"
        )

        with urllib.request.urlopen(
            req,
            timeout=10,
            context=ssl_context
        ) as response:
            return response.status < 400

    except Exception:
        return False


def fetch_json(req, retries=5):
    last_error = None

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(
                req,
                timeout=120,
                context=ssl_context
            ) as response:
                data = response.read().decode("utf-8")
                return json.loads(data)

        except Exception as error:
            last_error = error
            print(
                f"Request failed "
                f"(attempt {attempt + 1}/{retries}): {error}"
            )

            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))

    raise last_error


def run_sparql(query):
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

    return fetch_json(req)


def main():
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

    print("Fetching French painters from Wikidata...")

    result = run_sparql(query)
    bindings = result.get("results", {}).get("bindings", [])

    painters = []
    seen_ids = set()

    for item in bindings:
        person_uri = safe(
            item.get("person", {}).get("value")
        )

        if not person_uri:
            continue

        person_id = person_uri.rsplit("/", 1)[-1]

        if person_id in seen_ids:
            continue

        seen_ids.add(person_id)

        name = safe(
            item.get("personLabel", {}).get("value")
        )

        if not name:
            continue

        description = safe(
            item.get("description", {}).get("value")
        )

        website = safe(
            item.get("website", {}).get("value")
        )

        birth_date = safe(
            item.get("birthDate", {}).get("value")
        )

        death_date = safe(
            item.get("deathDate", {}).get("value")
        )

        birth_place = safe(
            item.get("birthPlaceLabel", {}).get("value")
        )

        coord = safe(
            item.get("coord", {}).get("value")
        )

        lat = None
        lon = None

        if coord.startswith("Point(") and coord.endswith(")"):
            try:
                values = coord[6:-1].split()
                lon = float(values[0])
                lat = float(values[1])
            except (ValueError, IndexError):
                lat = None
                lon = None

        website_valid = False

        if website:
            print(f"Checking website: {name}")
            website_valid = is_valid_website(website)

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
            "website_valid": website_valid,
            "description": description,
            "source": f"https://www.wikidata.org/wiki/{person_id}"
        }

        painters.append(painter)

    painters.sort(
        key=lambda painter: painter["name"].lower()
    )

    output = {
        "source": "Wikidata (CC0)",
        "license": "CC0 1.0",
        "country": "France",
        "type": "French painters",
        "count": len(painters),
        "painters": painters
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Done: {len(painters)} painters written to {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
