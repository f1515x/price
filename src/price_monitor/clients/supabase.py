"""Supabase REST helper; never log response bodies."""
import re

import requests

from price_monitor.settings import load_env


def request(method, table, *, params=None):
    values = load_env()
    url = values.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (values.get("SUPABASE_KEY") or values.get("SUPABASE_ANON_KEY", "")).strip()
    if not key or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/rest/v1)?", url):
        raise RuntimeError("请配置 SUPABASE_URL 和 SUPABASE_KEY")
    if not url.endswith("/rest/v1"):
        url += "/rest/v1"
    headers = {"apikey": key, "Accept": "application/json"}
    token = values.get("SUPABASE_ACCESS_TOKEN", "").strip()
    if token or not key.startswith("sb_"):
        headers["Authorization"] = "Bearer " + (token or key)
    try:
        response = requests.request(method, f"{url}/{table}", params=params,
                                    headers=headers, timeout=20)
        if not response.ok:
            raise RuntimeError(f"Supabase {table} 请求失败（HTTP {response.status_code}），请检查表结构和权限")
        return response.json() if response.content else None
    except (requests.RequestException, ValueError):
        raise RuntimeError(f"Supabase {table} 请求失败，请检查连接和返回格式") from None
