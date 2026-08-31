#!/usr/bin/env python3
"""
Snapshot Twitch par catégorie, streams FR uniquement.

Un run = un snapshot :
  data/YYYY-MM-DD.csv   -> une ligne par catégorie (≥ MIN_VIEWERS viewers cumulés)
  data/snapshots.csv    -> une ligne par run (totaux globaux, utile pour le contexte)

Variables d'env : TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET
Optionnel        : TWITCH_LANG (défaut "fr"), MIN_VIEWERS (défaut 100), DATA_DIR (défaut "data")
"""
import csv
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

CLIENT_ID = os.environ["TWITCH_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_CLIENT_SECRET"]
LANG = os.getenv("TWITCH_LANG", "fr")
MIN_VIEWERS = int(os.getenv("MIN_VIEWERS", "100"))
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
HELIX = "https://api.twitch.tv/helix"

FIELDS = [
    "ts_utc", "game_id", "game_name",
    "viewers", "channels", "avg_viewers", "median_viewers",
    "top1_viewers", "top1_share",
    "viewers_hors_top3", "channels_hors_top3", "avg_hors_top3",
    "channels_lt10",
]
SNAP_FIELDS = ["ts_utc", "lang", "streams_total", "viewers_total", "categories_kept", "duration_s"]


def get_app_token() -> str:
    r = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                "grant_type": "client_credentials"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def helix_get(session: requests.Session, path: str, params: dict) -> dict:
    for attempt in range(5):
        r = session.get(f"{HELIX}/{path}", params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:  # rate limit (800 pts/min en app token, on n'y arrive pas normalement)
            reset = int(r.headers.get("Ratelimit-Reset", "0"))
            time.sleep(max(1.0, reset - time.time()) + 1)
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    raise RuntimeError(f"Helix {path} : échec après 5 tentatives")


def fetch_all_streams(session: requests.Session) -> list[dict]:
    """Pagine toute la liste des streams live dans la langue cible.
    L'API est triée par viewers décroissants et bouge pendant la pagination :
    on déduplique sur l'id de stream."""
    streams, seen, cursor = [], set(), None
    while True:
        params = {"language": LANG, "first": 100}
        if cursor:
            params["after"] = cursor
        page = helix_get(session, "streams", params)
        data = page.get("data", [])
        for s in data:
            if s["id"] in seen or s.get("type") != "live":
                continue
            seen.add(s["id"])
            streams.append(s)
        cursor = page.get("pagination", {}).get("cursor")
        if not cursor or not data:
            break
    return streams


def aggregate(streams: list[dict], ts_iso: str) -> list[dict]:
    by_game: dict[tuple[str, str], list[int]] = defaultdict(list)
    for s in streams:
        key = (s.get("game_id") or "0", s.get("game_name") or "Sans catégorie")
        by_game[key].append(int(s["viewer_count"]))

    rows = []
    for (gid, gname), v in by_game.items():
        total = sum(v)
        if total < MIN_VIEWERS:
            continue
        v.sort(reverse=True)
        n = len(v)
        hors_top3_v = total - sum(v[:3])
        hors_top3_n = max(n - 3, 0)
        rows.append({
            "ts_utc": ts_iso,
            "game_id": gid,
            "game_name": gname,
            "viewers": total,
            "channels": n,
            "avg_viewers": round(total / n, 1),
            "median_viewers": statistics.median(v),
            "top1_viewers": v[0],
            "top1_share": round(v[0] / total, 3),
            "viewers_hors_top3": hors_top3_v,
            "channels_hors_top3": hors_top3_n,
            "avg_hors_top3": round(hors_top3_v / hors_top3_n, 1) if hors_top3_n else 0,
            "channels_lt10": sum(1 for x in v if x < 10),
        })
    rows.sort(key=lambda r: -r["viewers"])
    return rows


def append_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def main() -> None:
    t0 = time.time()
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    session = requests.Session()
    session.headers.update({"Client-Id": CLIENT_ID,
                            "Authorization": f"Bearer {get_app_token()}"})

    streams = fetch_all_streams(session)
    rows = aggregate(streams, ts.isoformat())

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    append_csv(DATA_DIR / f"{ts:%Y-%m-%d}.csv", rows, FIELDS)
    append_csv(DATA_DIR / "snapshots.csv", [{
        "ts_utc": ts.isoformat(),
        "lang": LANG,
        "streams_total": len(streams),
        "viewers_total": sum(int(s["viewer_count"]) for s in streams),
        "categories_kept": len(rows),
        "duration_s": round(time.time() - t0, 1),
    }], SNAP_FIELDS)

    print(f"{ts:%Y-%m-%d %H:%M} UTC — {len(streams)} streams '{LANG}', "
          f"{len(rows)} catégories ≥ {MIN_VIEWERS} viewers, {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
