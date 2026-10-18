"""Publish verified European source identities and the actual generated coverage."""
import hashlib
import json
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, DATA = ROOT / "data/raw", ROOT / "data"
SCOPE = {
    "de": "Germany; complete OSM ways may extend slightly across national borders.",
    "fr": "Metropolitan France including Corsica; no French overseas territories.",
    "ch": "Switzerland; complete OSM ways may extend slightly across national borders.",
    "es": "Spain including the Balearic and Canary Islands, Ceuta and Melilla.",
    "nl": "European Netherlands; no Caribbean territories.",
    "be": "Belgium; complete OSM ways may extend slightly across national borders.",
    "it": "Italy including Sicily and Sardinia.",
}


def country(code):
    with (RAW / f"extract_{code}.pkl").open("rb") as stream:
        extract = pickle.load(stream)  # Written locally by scripts/extract_osm.py.
    sources = []
    for row in extract["sources"]:
        file_path = RAW / row["file"]
        receipt = json.loads(file_path.with_name(file_path.name + ".source.json").read_text())
        with file_path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if (receipt["bytes"] != file_path.stat().st_size or receipt["sha256"] != digest
                or row.get("sha256") != digest or row["timestamp"] != receipt["timestamp"]):
            raise ValueError(f"{code}: source receipt/extraction/file identity differs for {file_path.name}")
        sources.append({"file": file_path.name, **{key: receipt[key] for key in
                        ("url", "bytes", "timestamp", "sha256", "md5", "etag", "last_modified")}})
    coords = [point for _, _, points in extract["ways"] for point in points]
    facts = json.loads((DATA / f"{code}_facts.json").read_text())
    counts = {layer: len(json.loads((DATA / f"{code}_{layer}.geojson").read_text())["features"])
              for layer in ("rail", "metro", "build", "stations", "yards", "depots")}
    return {
        "scope": SCOPE[code], "sources": sources,
        "urban_source_notes": [row for row in json.loads((DATA / "europe_urban_sources.json").read_text())
                               if row["g"] == code],
        "raw_railway_bounds": [min(p[0] for p in coords), min(p[1] for p in coords),
                               max(p[0] for p in coords), max(p[1] for p in coords)],
        "generated": {"facts": facts, "feature_counts": counts},
        "naming": "Local OSM infrastructure names; unnamed track remains unlabelled.",
        "speeds": "Source design tags and operating maxspeed remain distinct; operating limits are marked e.",
    }


def main():
    result = {
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL 1.0",
        "license_url": "https://www.openstreetmap.org/copyright",
        "countries": {code: country(code) for code in SCOPE},
    }
    file_path = DATA / "europe_sources.json"
    file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{file_path.name}: all source files, receipts and extraction hashes agree")


if __name__ == "__main__":
    main()
