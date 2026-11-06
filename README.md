# PulseDesk

PulseDesk is a Flask help-desk prototype for tracking branch IT support tickets. It includes role-based demo accounts, ticket management, incident alerts, update tracking, and CSV reports.

## Requirements

- Python 3.11 or newer

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

Open <http://127.0.0.1:5000>. On first run, the app creates `support.db` and seeds the demo users and branches.

## Demo accounts

All accounts use the demo password `demo123`:

- Officer: `officer@pulsedesk.test`
- Supervisor: `supervisor@pulsedesk.test`
- Administrator: `admin@pulsedesk.test`

## Tests

Install pytest in the active environment, then run the smoke tests:

```powershell
py -m pip install pytest
py -m pytest test_smoke.py -q
```

## Render deployment

`render.yaml` configures the web service to install `requirements.txt` and start with `gunicorn app:app`. Render generates the `SECRET_KEY` environment variable. Deploy the branch connected to the Render service; if automatic deploys are disabled, use **Manual Deploy → Deploy latest commit** in Render.

The stylesheet is served from `static/style.css`. Its URL includes a hash of the file contents, so a CSS change produces a new URL and avoids reusing an older cached stylesheet.

## Project layout

- `app.py`: Flask routes, authentication, database models, and alert detection
- `templates/`: server-rendered HTML pages
- `static/style.css`: application styles
- `test_smoke.py`: authentication and page smoke tests
- `requirements.txt`: runtime Python dependencies
- `render.yaml`: Render build and start configuration
- `support.db`: local SQLite data, created at runtime and ignored by Git

To generate sample tickets and alerts, sign in as the Administrator and select **Generate demo activity** on the dashboard.
