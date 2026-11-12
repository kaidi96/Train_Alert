"""Streamlit UI: define train watches (route, date, time zone), set price alerts."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, available_timezones

import pandas as pd
import streamlit as st

import store
from monitor import ALERT_KINDS, CHECK_INTERVAL, Monitor, check_all

st.set_page_config(page_title="Train Price Alert", page_icon=":train:", layout="wide")


@st.cache_resource
def start_monitor():
    monitor = Monitor()
    monitor.start()
    return monitor


start_monitor()
TIMEZONES = sorted(available_timezones())


def fmt_local(iso, tz):
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ---------- Sidebar: new watch ----------
with st.sidebar:
    st.header("New watch")
    with st.form("new_watch", clear_on_submit=False):
        origin = st.text_input("From", placeholder="Paris")
        destination = st.text_input("To", placeholder="Lyon")
        day = st.date_input("Travel date", value=date.today() + timedelta(days=7), min_value=date.today())
        tz = st.selectbox("Time zone", TIMEZONES, index=TIMEZONES.index("Europe/Paris"))
        c1, c2 = st.columns(2)
        t_from = c1.time_input("Earliest", value=time(0, 0))
        t_to = c2.time_input("Latest", value=time(23, 59))
        if st.form_submit_button("Start watching", type="primary"):
            if not origin.strip() or not destination.strip():
                st.error("Enter both From and To.")
            elif t_from > t_to:
                st.error("Earliest must be before latest.")
            else:
                with store.transaction() as data:
                    data["watches"].append({
                        "id": uuid.uuid4().hex[:8],
                        "origin": origin.strip(), "destination": destination.strip(),
                        "date": day.isoformat(), "tz": tz,
                        "time_from": t_from.strftime("%H:%M"), "time_to": t_to.strftime("%H:%M"),
                        "active": True, "last_check": None, "last_error": None, "last_offers": [],
                    })
                check_all()
                st.rerun()

    st.caption(f"Prices are checked every {CHECK_INTERVAL // 60} minutes.")
    if st.button("Check now"):
        check_all()
        st.rerun()


# ---------- Main ----------
st.title("Train Price Alert")


@st.fragment(run_every=30)
def dashboard():
    data = store.load()

    if data["events"]:
        with st.expander(f"Triggered alerts ({len(data['events'])})", expanded=True):
            for ev in reversed(data["events"][-10:]):
                st.success(f"{ev['ts'][:19].replace('T', ' ')} UTC - {ev['message']}")

    if not data["watches"]:
        st.info("Add a route in the sidebar to start tracking prices.")
        return

    for w in data["watches"]:
        title = f"{w['origin']} -> {w['destination']} | {w['date']} | {w['time_from']}-{w['time_to']} ({w['tz']})"
        if not w["active"]:
            title += " [paused]"
        with st.expander(title, expanded=True):
            history = data["history"].get(w["id"], [])
            left, right = st.columns([2, 1])

            with left:
                if w.get("last_error"):
                    st.error(w["last_error"])
                if history:
                    st.metric("Cheapest now", f"{history[-1]['min_price']:.2f}",
                              delta=f"{history[-1]['min_price'] - history[-2]['min_price']:.2f}"
                              if len(history) > 1 else None, delta_color="inverse")
                    df = pd.DataFrame(history)
                    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert(w["tz"])
                    st.line_chart(df.set_index("ts")["min_price"])
                if w["last_offers"]:
                    st.dataframe(pd.DataFrame([{
                        "Departure": fmt_local(o["departure"], w["tz"]),
                        "Arrival": fmt_local(o["arrival"], w["tz"]),
                        "Train": o["train"], "Price": o["price"], "Currency": o["currency"],
                    } for o in sorted(w["last_offers"], key=lambda o: o["price"])]),
                        hide_index=True, use_container_width=True)
                if w["last_check"]:
                    st.caption(f"Last check: {fmt_local(w['last_check'], w['tz'])} ({w['tz']})")

            with right:
                st.subheader("Alerts")
                for a in [a for a in data["alerts"] if a["watch_id"] == w["id"]]:
                    label = f"{ALERT_KINDS[a['kind']]} {a['value']}"
                    cols = st.columns([3, 1, 1])
                    if a["status"] == "triggered":
                        cols[0].write(f"{label}  \nTriggered at {a['triggered_price']:.2f}")
                        if cols[1].button("Re-arm", key=f"rearm_{a['id']}"):
                            with store.transaction() as d:
                                for x in d["alerts"]:
                                    if x["id"] == a["id"]:
                                        x["status"] = "active"
                            st.rerun(scope="fragment")
                    else:
                        cols[0].write(label)
                    if cols[2].button("Delete", key=f"delalert_{a['id']}"):
                        with store.transaction() as d:
                            d["alerts"] = [x for x in d["alerts"] if x["id"] != a["id"]]
                        st.rerun(scope="fragment")

                with st.form(f"alert_form_{w['id']}", clear_on_submit=True):
                    kind = st.selectbox("Type", list(ALERT_KINDS), format_func=ALERT_KINDS.get,
                                        key=f"kind_{w['id']}")
                    value = st.number_input("Value", min_value=0.0, value=30.0, step=1.0,
                                            key=f"val_{w['id']}")
                    if st.form_submit_button("Add alert"):
                        with store.transaction() as d:
                            d["alerts"].append({
                                "id": uuid.uuid4().hex[:8], "watch_id": w["id"], "kind": kind,
                                "value": value, "status": "active",
                                "triggered_at": None, "triggered_price": None,
                            })
                        st.rerun(scope="fragment")

                b1, b2 = st.columns(2)
                if b1.button("Resume" if not w["active"] else "Pause", key=f"pause_{w['id']}"):
                    with store.transaction() as d:
                        for x in d["watches"]:
                            if x["id"] == w["id"]:
                                x["active"] = not x["active"]
                    st.rerun(scope="fragment")
                if b2.button("Delete watch", key=f"delwatch_{w['id']}"):
                    with store.transaction() as d:
                        d["watches"] = [x for x in d["watches"] if x["id"] != w["id"]]
                        d["alerts"] = [x for x in d["alerts"] if x["watch_id"] != w["id"]]
                        d["history"].pop(w["id"], None)
                    st.rerun(scope="fragment")


dashboard()
