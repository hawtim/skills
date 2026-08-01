#!/usr/bin/env python3
"""Bounded M-Team FREE candidate discovery and one-torrent qBittorrent add."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

GIB = 1024 ** 3


def request(url, *, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("mteam_base", "mteam_api_key", "qbittorrent_url", "save_path"):
        if not config.get(key):
            raise SystemExit(f"Missing config field: {key}")
    return config


def mt_post(config, path, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "x-api-key": config["mteam_api_key"], "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 MTeamFreeSeedCycle/1.0", "Origin": "https://kp.m-team.cc", "Referer": "https://kp.m-team.cc/",
    }
    data = json.loads(request(config["mteam_base"].rstrip("/") + path, method="POST", headers=headers, body=body))
    if str(data.get("code")) != "0":
        raise RuntimeError(data.get("message") or "M-Team API request failed")
    return data.get("data")


def qb_json(config, path):
    return json.loads(request(config["qbittorrent_url"].rstrip("/") + "/api/v2" + path))


def newest(config):
    return mt_post(config, "/torrent/search", {"mode": "normal", "categories": [], "keyword": "", "pageNumber": 1, "pageSize": 50, "visible": 1}).get("data", [])


def active_downloads(rows):
    downloading = {"downloading", "metaDL", "forcedDL", "stalledDL", "queuedDL", "allocating", "checkingDL"}
    return sum(row.get("state") in downloading for row in rows)


def candidate(row):
    status = row.get("status") or {}
    return {
        "id": str(row["id"]), "name": row.get("name", ""), "size": int(row.get("size") or 0),
        "created": row.get("createdDate"), "discount": status.get("discount"),
        "seeders": int(status.get("seeders") or 0), "leechers": int(status.get("leechers") or 0),
        "visible": bool(status.get("visible")), "banned": bool(status.get("banned")),
        "discount_end": status.get("discountEndTime"),
    }


def score(item):
    if item["discount"] != "FREE" or not item["visible"] or item["banned"]:
        return None
    size_gib = item["size"] / GIB
    if not 0.25 <= size_gib <= 10:
        return None
    try:
        age = max(0, (dt.datetime.now() - dt.datetime.strptime(item["created"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60)
    except (TypeError, ValueError):
        age = 999
    freshness = max(0, 30 - age) / 30
    demand = min(item["leechers"] / 20, 1)
    competition = min(item["seeders"] / 30, 1)
    return round(35 * freshness + 35 * demand + 10 * min(size_gib / 5, 1) - 20 * competition, 1)


def print_preview(config):
    rows = qb_json(config, "/torrents/info")
    usage = shutil.disk_usage(config["save_path"])
    output = []
    for raw in newest(config):
        item = candidate(raw)
        item["score"] = score(item)
        if item["score"] is not None:
            item["size_gib"] = round(item.pop("size") / GIB, 2)
            output.append(item)
    output.sort(key=lambda item: item["score"], reverse=True)
    print(json.dumps({"active_downloads": active_downloads(rows), "free_gib": round(usage.free / GIB, 2), "candidates": output[:12]}, ensure_ascii=False, indent=2))


def download_torrent(config, torrent_id):
    url = mt_post(config, f"/torrent/genDlToken?id={urllib.parse.quote(torrent_id)}", {})
    if not isinstance(url, str) or not url.startswith("http"):
        raise RuntimeError("M-Team returned an invalid download URL")
    headers = {
        "x-api-key": config["mteam_api_key"], "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 MTeamFreeSeedCycle/1.0", "Origin": "https://kp.m-team.cc", "Referer": "https://kp.m-team.cc/",
    }
    torrent = request(url, headers=headers)
    if not torrent.startswith(b"d"):
        try:
            message = json.loads(torrent).get("message")
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = "response was not a bencoded torrent file"
        raise RuntimeError(f"M-Team torrent download failed: {message}")
    return torrent


def add_to_qb(config, torrent):
    boundary = "----MTeamCrossSeedBoundary7d25c"
    fields = {"savepath": config["save_path"], "paused": "false", "tags": "mteam-free-cycle", "contentLayout": "Original"}
    chunks = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode() for key, value in fields.items()]
    chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"torrents\"; filename=\"mteam.torrent\"\r\nContent-Type: application/x-bittorrent\r\n\r\n".encode() + torrent + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    response = request(config["qbittorrent_url"].rstrip("/") + "/api/v2/torrents/add", method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, body=b"".join(chunks))
    if response.strip() not in (b"Ok.", b""):
        raise RuntimeError(f"qBittorrent add failed: {response[:200]!r}")


def add(config, torrent_id, confirmed):
    if not confirmed:
        raise SystemExit("Refusing write: repeat with --confirm after previewing the candidate.")
    choices = {str(row["id"]): candidate(row) for row in newest(config)}
    item = choices.get(torrent_id)
    if not item or score(item) is None:
        raise SystemExit("Refusing write: ID is not a current eligible FREE candidate.")
    rows = qb_json(config, "/torrents/info")
    if active_downloads(rows) >= int(config.get("max_active_downloads", 3)):
        raise SystemExit("Refusing write: active-download limit reached.")
    if item["size"] > int(float(config.get("max_torrent_gib", 10)) * GIB):
        raise SystemExit("Refusing write: one-torrent size limit exceeded.")
    if shutil.disk_usage(config["save_path"]).free < item["size"] * 1.3:
        raise SystemExit("Refusing write: insufficient free disk space.")
    add_to_qb(config, download_torrent(config, torrent_id))
    print(json.dumps({"added": torrent_id, "name": item["name"], "size_gib": round(item["size"] / GIB, 2), "tag": "mteam-free-cycle"}, ensure_ascii=False))


def status(config, info_hash):
    row = qb_json(config, "/torrents/info?hashes=" + urllib.parse.quote(info_hash))[0]
    peers = qb_json(config, "/sync/torrentPeers?hash=" + urllib.parse.quote(info_hash)).get("peers", {}).values()
    incomplete = sum(float(peer.get("progress") or 0) < 1 for peer in peers)
    print(json.dumps({"state": row.get("state"), "progress": row.get("progress"), "dlspeed": row.get("dlspeed"), "upspeed": row.get("upspeed"), "uploaded": row.get("uploaded"), "connected_peers": len(peers), "incomplete_peers": incomplete}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "add", "status"):
        child = sub.add_parser(name)
        child.add_argument("--config", required=True)
    sub.choices["add"].add_argument("--id", required=True)
    sub.choices["add"].add_argument("--confirm", action="store_true")
    sub.choices["status"].add_argument("--hash", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "preview": print_preview(config)
    elif args.command == "add": add(config, args.id, args.confirm)
    else: status(config, args.hash)


if __name__ == "__main__":
    main()
