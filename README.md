# Train Price Alert

Streamlit app that checks train prices every 5 minutes for routes you define, and fires alerts.

## Run

```powershell
cd C:\PE_Builds\Train_Alert
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The monitor runs while the app process is running.

## Usage

- Sidebar: From, To, travel date, time zone, departure window, then "Start watching".
- Per route: add alerts (price at or below / at or above / drop of N % since last check). Triggered alerts show in the UI and can be re-armed.

## Price source

Default is `TRAIN_PROVIDER=demo` (simulated prices, for testing the UI and alerts).
For real prices, point to a JSON API you have access to:

```powershell
$env:TRAIN_PROVIDER = "http"
$env:TRAIN_API_URL = "https://example.com/trips?from={origin}&to={destination}&date={date}"
$env:TRAIN_API_KEY = "..."   # optional, sent as Bearer token
```

The API must return a JSON list of `{"departure", "arrival", "price", "currency", "train"}` (ISO datetimes).
To use a different API, adapt `http_offers` in `providers.py`.

## Optional email notification

Set `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`.
