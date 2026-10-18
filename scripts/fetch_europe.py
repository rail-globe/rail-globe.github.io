"""Download full OSM country snapshots, resuming verified HTTP byte ranges.

    python3 scripts/fetch_europe.py de fr es --workers 24

Raw files and range caches stay in data/raw/ (not published). A source receipt
records the URL, HTTP snapshot identity, SHA256 and PBF replication timestamp.
Germany uses GWDG's Geofabrik mirror; the other countries use OSM France.
"""
import argparse
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://download.openstreetmap.fr/extracts/europe/"
SOURCES = {
    "de": ("germany-latest.osm.pbf",
           "https://ftp5.gwdg.de/pub/misc/openstreetmap/download.geofabrik.de/germany-latest.osm.pbf"),
    "fr": ("france-latest.osm.pbf", BASE + "france.osm.pbf"),
    "ch": ("switzerland-latest.osm.pbf", BASE + "switzerland.osm.pbf"),
    "es": ("spain-latest.osm.pbf", BASE + "spain.osm.pbf"),
    "nl": ("netherlands-latest.osm.pbf", BASE + "netherlands.osm.pbf"),
    "be": ("belgium-latest.osm.pbf", BASE + "belgium.osm.pbf"),
    "it": ("italy-latest.osm.pbf", BASE + "italy.osm.pbf"),
    "es-canarias": ("canarias-latest.osm.pbf",
                    "https://download.openstreetmap.fr/extracts/africa/spain/canarias.osm.pbf"),
    "es-ceuta": ("ceuta-latest.osm.pbf",
                 "https://download.openstreetmap.fr/extracts/africa/spain/ceuta.osm.pbf"),
    "es-melilla": ("melilla-latest.osm.pbf",
                   "https://download.openstreetmap.fr/extracts/africa/spain/melilla.osm.pbf"),
}
HEADERS = {"User-Agent": "RailGlobe-data-builder/1.0 (https://rail-globe.github.io)",
           "Accept-Encoding": "identity"}
CHUNK = 8 * 1024 * 1024


def atomic_json(file_path, value):
    temp = file_path.with_name(file_path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, file_path)


def fetch(code, workers):
    name, url = SOURCES[code]
    out = RAW / name
    RAW.mkdir(parents=True, exist_ok=True)
    with requests.head(url, headers=HEADERS, timeout=(15, 30)) as reply:
        reply.raise_for_status()
        identity = {"url": url, "bytes": int(reply.headers["Content-Length"]),
                    "etag": reply.headers.get("ETag"),
                    "last_modified": reply.headers.get("Last-Modified"), "chunk_bytes": CHUNK}
    if not identity["etag"] or identity["etag"].startswith("W/"):
        raise RuntimeError(f"{code}: source has no strong ETag; cannot bind range parts")
    receipt = out.with_name(out.name + ".source.json")
    if out.exists() and receipt.exists():
        saved = json.loads(receipt.read_text())
        if all(saved.get(k) == v for k, v in identity.items()) and out.stat().st_size == identity["bytes"]:
            with out.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest == saved.get("sha256"):
                print(f"{code}: existing snapshot verified {digest}", flush=True)
                return
    parts = out.with_name(out.name + ".ranges")
    parts.mkdir(exist_ok=True)
    manifest = parts / "source.json"
    if manifest.exists() and json.loads(manifest.read_text()) != identity:
        raise RuntimeError(f"{code}: snapshot changed; preserve the old ranges and start a fresh cache")
    atomic_json(manifest, identity)
    total = identity["bytes"]

    def get(row):
        index, first, last = row
        part = parts / f"{index:05d}"
        want = last - first + 1
        if part.exists() and part.stat().st_size == want:
            return want
        temp = part.with_name(part.name + ".tmp")
        for attempt in range(6):
            have = temp.stat().st_size if temp.exists() else 0
            if have >= want:
                temp.unlink()
                have = 0
            start = first + have
            try:
                headers = {**HEADERS, "Range": f"bytes={start}-{last}",
                           "If-Match": identity["etag"]}
                with requests.get(url, headers=headers, stream=True, timeout=(15, 90)) as reply:
                    if reply.status_code == 412:
                        raise ValueError("source snapshot changed during download")
                    reply.raise_for_status()
                    expected = f"bytes {start}-{last}/{total}"
                    if (reply.status_code != 206 or reply.headers.get("Content-Range") != expected
                            or reply.headers.get("ETag") != identity["etag"]):
                        raise ValueError(f"unbound range response: {reply.status_code} {reply.headers.get('Content-Range')}")
                    with temp.open("ab" if have else "wb") as stream:
                        for block in reply.iter_content(256 * 1024):
                            if stream.tell() + len(block) > want:
                                raise ValueError("range response is longer than requested")
                            stream.write(block)
                if temp.stat().st_size != want:
                    raise IOError("short range response")
                os.replace(temp, part)
                return want
            except ValueError:
                raise
            except (requests.RequestException, OSError):
                if attempt == 5:
                    raise
                time.sleep(min(15, 2 ** attempt))

    ranges = [(i, start, min(total - 1, start + CHUNK - 1))
              for i, start in enumerate(range(0, total, CHUNK))]
    begun = time.monotonic()
    print(f"{code}: {total / 1e9:.2f} GB, {len(ranges)} ranges, {workers} connections; {identity['etag']}", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(get, row) for row in ranges]
        checked = 0
        for future in as_completed(pending):
            checked += future.result()
            if checked == total or checked % (CHUNK * 8) == 0:
                elapsed = time.monotonic() - begun
                print(f"{code}: verified {checked / total:.1%}, {checked / 1e6:.0f} MB, "
                      f"{elapsed:.0f}s", flush=True)
    temp = out.with_name(out.name + ".tmp")
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with temp.open("wb") as stream:
        for index, _, _ in ranges:
            with (parts / f"{index:05d}").open("rb") as source:
                while block := source.read(1024 * 1024):
                    sha.update(block)
                    md5.update(block)
                    stream.write(block)
    if temp.stat().st_size != total:
        raise RuntimeError(f"{code}: assembled size mismatch")
    with requests.get(url + ".md5", headers=HEADERS, timeout=(15, 30)) as reply:
        reply.raise_for_status()
        expected = re.match(r"[0-9a-fA-F]{32}", reply.text)
    if not expected or md5.hexdigest() != expected[0].lower():
        raise RuntimeError(f"{code}: source MD5 does not match the assembled snapshot")
    import osmium
    with osmium.io.Reader(osmium.io.File(str(temp), "pbf")) as reader:
        header = reader.header()
        identity["timestamp"] = header.get("osmosis_replication_timestamp")
        identity["replication_url"] = header.get("osmosis_replication_base_url")
    identity.update({"sha256": sha.hexdigest(), "md5": md5.hexdigest(), "country": code})
    os.replace(temp, out)
    atomic_json(receipt, identity)
    # The complete file and receipt now contain everything needed to resume.
    for index, _, _ in ranges:
        (parts / f"{index:05d}").unlink()
    print(f"{code}: READY {out.name} sha256={identity['sha256']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codes", nargs="+", choices=tuple(SOURCES))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--ipv4", action="store_true", help="use IPv4 when the source's IPv6 route is slow")
    args = parser.parse_args()
    if not 1 <= args.workers <= 48:
        parser.error("--workers must be between 1 and 48")
    if args.ipv4:
        import socket
        import urllib3.util.connection
        urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
    codes = list(dict.fromkeys(args.codes))
    if "es" in codes:
        # The Europe extract excludes Spain's African territories, including Tenerife's trams.
        codes += [code for code in ("es-canarias", "es-ceuta", "es-melilla") if code not in codes]
    with ThreadPoolExecutor(max_workers=len(codes)) as countries:
        jobs = [countries.submit(fetch, code, args.workers) for code in codes]
        for job in as_completed(jobs):
            job.result()
