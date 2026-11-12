"""Train price providers. Each returns a list of offers:
{"departure": ISO with offset, "arrival": ISO with offset, "price": float, "currency": str, "train": str}
"""

import hashlib
import math
import os
import random
from datetime import date as date_cls, datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

PROVIDERS = ["demo", "http"]


def _seed(text):
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def demo_offers(origin, destination, day, tz, now):
    """Simulated prices: stable per route/train, drifting every 5 minutes."""
    zone = ZoneInfo(tz)
    route_seed = _seed(f"{origin.lower()}|{destination.lower()}")
    base = 25 + route_seed % 90
    duration = timedelta(minutes=60 + route_seed % 180)
    bucket = int(now.timestamp() // 300)
    days_left = max((day - now.astimezone(zone).date()).days, 0)
    urgency = 1 + 0.5 * max(0.0, 1 - days_left / 30)
    offers = []
    for minutes in range(5 * 60, 22 * 60 + 1, 30):
        dep = datetime.combine(day, time(minutes // 60, minutes % 60), tzinfo=zone)
        peak = 1.25 if dep.hour in (7, 8, 17, 18) else 1.0
        drift = 0.08 * math.sin(bucket / 7 + minutes)
        rng = random.Random(f"{route_seed}|{minutes}|{bucket}")
        price = base * peak * urgency * (1 + drift + rng.uniform(-0.02, 0.02))
        offers.append({
            "departure": dep.isoformat(),
            "arrival": (dep + duration).isoformat(),
            "price": round(price, 2),
            "currency": "EUR",
            "train": f"TR{minutes // 30:03d}",
        })
    return offers


def http_offers(origin, destination, day, tz):
    """Generic JSON API. Set TRAIN_API_URL with {origin}, {destination}, {date} placeholders.

    Expected response: a JSON list of objects with departure, arrival, price
    (and optional currency, train). Optional TRAIN_API_KEY is sent as a Bearer token.
    """
    url = os.environ.get("TRAIN_API_URL", "")
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("TRAIN_API_URL is not set (must start with http:// or https://)")
    url = url.format(origin=quote(origin), destination=quote(destination), date=day.isoformat())
    headers = {}
    if os.environ.get("TRAIN_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['TRAIN_API_KEY']}"
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    zone = ZoneInfo(tz)
    offers = []
    for item in resp.json():
        dep = datetime.fromisoformat(item["departure"])
        arr = datetime.fromisoformat(item["arrival"])
        offers.append({
            "departure": (dep if dep.tzinfo else dep.replace(tzinfo=zone)).isoformat(),
            "arrival": (arr if arr.tzinfo else arr.replace(tzinfo=zone)).isoformat(),
            "price": float(item["price"]),
            "currency": item.get("currency", "EUR"),
            "train": str(item.get("train", "")),
        })
    return offers


def fetch_offers(watch, now):
    """Fetch offers for a watch, filtered to its departure time window (in the watch time zone)."""
    day = date_cls.fromisoformat(watch["date"])
    provider = os.environ.get("TRAIN_PROVIDER", "demo")
    if provider == "http":
        offers = http_offers(watch["origin"], watch["destination"], day, watch["tz"])
    else:
        offers = demo_offers(watch["origin"], watch["destination"], day, watch["tz"], now)
    zone = ZoneInfo(watch["tz"])
    start, end = watch["time_from"], watch["time_to"]
    return [
        o for o in offers
        if start <= datetime.fromisoformat(o["departure"]).astimezone(zone).strftime("%H:%M") <= end
    ]
