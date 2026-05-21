# HubSpot KPI Dashboard

A Streamlit dashboard that pulls live data from the HubSpot API to track:

- **Email campaigns** — sends, deliveries, opens, clicks, bounces, unsubscribes (with time-series)
- **Engagement** — recent email activity with open / reply counts
- **Documents** — which attached documents are being sent and opened

> ⚠️ HubSpot's public API does **not** expose per-page time-spent data for documents
> attached via the native Documents tool. That metric is visible in the Sales Content
> Analytics UI but not via API. To get it programmatically, use a third-party tool
> like CloudFiles or export the CSV manually.

---

## 1. Create the HubSpot private app

1. In HubSpot, go to **Settings → Integrations → Private Apps → Create private app**
2. Under **Scopes**, enable:
   - `content`
   - `marketing-email`
   - `crm.objects.contacts.read`
   - `sales-email-read`
3. Click **Create app**, then **Show token** and copy it (starts with `pat-na1-...`)

Keep this token secret. It's the equivalent of a password to your portal.

## 2. Run locally

```bash
git clone <your-repo-url>
cd hubspot-kpi-dashboard

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit secrets.toml and paste your token

streamlit run streamlit_app.py
```

The app opens at `http://localhost:8501`.

## 3. Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (public or private — your call).
2. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**.
3. Point it at your repo, branch `main`, file `streamlit_app.py`.
4. In **Advanced settings → Secrets**, paste:
   ```toml
   hubspot_token = "pat-na1-your-real-token"
   ```
5. Deploy.

The app URL will be public, but your token lives only in Streamlit's secrets vault
and is never exposed to visitors.

## 4. Project layout

```
hubspot-kpi-dashboard/
├── streamlit_app.py             # main dashboard UI
├── hubspot_client.py            # API wrapper + caching
├── requirements.txt
├── .streamlit/
│   └── secrets.toml.example     # template (real one is gitignored)
├── .gitignore
└── README.md
```

## 5. Extending the dashboard

- **More KPIs:** add functions to `hubspot_client.py` and wire them into new tabs in `streamlit_app.py`.
- **Time-spent data (later):** drop a CSV into the repo (e.g. `data/document_views.csv`) and read it with `pandas.read_csv`. The dashboard can blend it with the live engagement data.
- **Scheduled snapshots:** add a GitHub Actions workflow that calls the HubSpot API nightly and commits a CSV — useful for historical trending beyond what the API window allows.

## 6. Rate limits

The free Streamlit cache (`@st.cache_data(ttl=600)`) holds responses for 10 minutes.
HubSpot's standard rate limit is 100 requests per 10 seconds per private app, which
is plenty for this dashboard's traffic patterns. The client also retries on `429`
with exponential backoff.
