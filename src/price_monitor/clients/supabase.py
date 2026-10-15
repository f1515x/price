"""Supabase credential storage; never log response bodies."""
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


def load_credentials():
    # Match Orders3 exactly, including the '=' in column names.
    rows = request("GET", "secret", params={"select": "*"})
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError("Supabase secret 表必须返回唯一一条对象记录")
    result = []
    for field in ("API_KEY=", "API_SECRET="):
        value = rows[0].get(field)
        if not isinstance(value, str):
            raise RuntimeError(f"Supabase secret 表的 {field} 无效")
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1].strip()
        if not value or len(value) > 4096 or any(c in value for c in "\n\r\0"):
            raise RuntimeError(f"Supabase secret 表的 {field} 无效")
        result.append(value)
    return tuple(result)
