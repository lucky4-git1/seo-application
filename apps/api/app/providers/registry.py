"""Provider registry — what the platform supports and what each needs.

Adding a vendor = new module implementing the Protocol + one entry here.
Business logic only talks to Protocols via services (app/serp.py,
app/keywords.py), never to these classes directly.
"""
from __future__ import annotations

PROVIDERS: dict[str, dict] = {
    "dataforseo": {
        "label": "DataForSEO",
        "kind": ["serp", "keyword"],
        "fields": [
            {"name": "login", "label": "API login", "secret": False},
            {"name": "password", "label": "API password", "secret": True},
        ],
        "docs": "https://docs.dataforseo.com/v3/appendix/getting-started/",
    },
    "google_ads": {
        "label": "Google Ads (Keyword Planner)",
        "kind": ["keyword"],
        "fields": [
            {"name": "developer_token", "label": "Developer token", "secret": True},
            {"name": "client_id", "label": "OAuth client ID", "secret": False},
            {"name": "client_secret", "label": "OAuth client secret", "secret": True},
            {"name": "refresh_token", "label": "Refresh token", "secret": True},
            {"name": "customer_id", "label": "Customer ID", "secret": False},
        ],
        "docs": "https://developers.google.com/google-ads/api/docs/start",
        "status": "planned",
    },
}


def required_fields(provider: str) -> list[str]:
    meta = PROVIDERS.get(provider)
    if meta is None:
        raise KeyError(f"unknown provider: {provider}")
    return [f["name"] for f in meta["fields"]]


def validate_credentials(provider: str, creds: dict) -> None:
    missing = [f for f in required_fields(provider) if not (creds.get(f) or "").strip()]
    if missing:
        raise ValueError(f"missing credential fields: {', '.join(missing)}")
