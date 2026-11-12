"""Background monitor: polls prices every CHECK_INTERVAL seconds and evaluates alerts."""

import logging
import os
import smtplib
import threading
from datetime import date as date_cls, datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import store
from providers import fetch_offers

CHECK_INTERVAL = 300
ALERT_KINDS = {
    "below": "Price at or below",
    "above": "Price at or above",
    "drop_pct": "Drop of at least (%) since last check",
}

log = logging.getLogger("train_alert")


def _send_email(subject, body):
    """Optional: set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO."""
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("ALERT_EMAIL_TO")
    if not host or not to:
        return
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, to
    msg["From"] = os.environ.get("SMTP_USER", to)
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls()
            if os.environ.get("SMTP_USER"):
                smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            smtp.send_message(msg)
    except Exception:
        log.exception("Email notification failed")


def _is_triggered(alert, price, prev_price):
    if alert["kind"] == "below":
        return price <= alert["value"]
    if alert["kind"] == "above":
        return price >= alert["value"]
    if alert["kind"] == "drop_pct" and prev_price:
        return (prev_price - price) / prev_price * 100 >= alert["value"]
    return False


def check_all(now=None):
    """Fetch prices for every active watch, record history, fire alerts."""
    now = now or datetime.now(timezone.utc)
    watches = [w for w in store.load()["watches"] if w["active"]]

    results = {}
    for w in watches:
        try:
            results[w["id"]] = (fetch_offers(w, now), None)
        except Exception as exc:
            log.exception("Fetch failed for %s", w["id"])
            results[w["id"]] = ([], str(exc))

    notifications = []
    with store.transaction() as data:
        for w in data["watches"]:
            if w["id"] not in results:
                continue
            offers, error = results[w["id"]]
            w["last_check"] = now.isoformat()
            w["last_error"] = error
            if error:
                continue
            w["last_offers"] = offers
            if date_cls.fromisoformat(w["date"]) < now.astimezone(ZoneInfo(w["tz"])).date():
                w["active"] = False
            if not offers:
                continue
            best = min(offers, key=lambda o: o["price"])
            history = data["history"].setdefault(w["id"], [])
            prev_price = history[-1]["min_price"] if history else None
            history.append({"ts": now.isoformat(), "min_price": best["price"]})

            for a in data["alerts"]:
                if a["watch_id"] == w["id"] and a["status"] == "active" \
                        and _is_triggered(a, best["price"], prev_price):
                    a["status"] = "triggered"
                    a["triggered_at"] = now.isoformat()
                    a["triggered_price"] = best["price"]
                    text = (f"{w['origin']} -> {w['destination']} on {w['date']}: "
                            f"{best['price']:.2f} {best['currency']} "
                            f"({ALERT_KINDS[a['kind']]} {a['value']})")
                    data["events"].append({"ts": now.isoformat(), "watch_id": w["id"], "message": text})
                    notifications.append(text)

    for text in notifications:
        _send_email("Train price alert", text)
    return notifications


class Monitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="train-monitor")
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                check_all()
            except Exception:
                log.exception("Monitor cycle failed")
            self._stop_event.wait(CHECK_INTERVAL)

    def stop(self):
        self._stop_event.set()
