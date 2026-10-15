"""Supabase credential and contract storage; never log response bodies."""
from decimal import Decimal, InvalidOperation
import re

import requests

from price_monitor.settings import load_env


def request(method, table, *, params=None, data=None):
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
    if data is not None:
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        response = requests.request(method, f"{url}/{table}", params=params,
                                    json=data, headers=headers, timeout=20)
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


def contract_name(value):
    value = value.strip().upper().replace("-", "_")
    if "_" not in value:
        value += "_USDT"
    if not re.fullmatch(r"[A-Z0-9_]+_USDT", value):
        raise ValueError("合约名称无效，仅支持 USDT 合约")
    return value


def validate_contract(contract, row):
    if not isinstance(row, dict) or row.get("contract", row.get("name")) != contract:
        raise RuntimeError(f"{contract} 的合约记录不匹配")
    record = {"contract": contract}
    for field in ("quanto_multiplier", "order_price_round", "leverage_max"):
        value = row.get(field)
        # Gate returns decimal strings. Reject floats instead of preserving already lost precision.
        if not isinstance(value, str):
            raise RuntimeError(f"{contract} 的 {field} 必须是数字字符串")
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise RuntimeError(f"{contract} 的 {field} 无效") from None
        if not number.is_finite() or number <= 0:
            raise RuntimeError(f"{contract} 的 {field} 必须为正数")
        if field == "leverage_max" and number != number.to_integral_value():
            raise RuntimeError(f"{contract} 的 leverage_max 必须为整数")
        record[field] = value
    return record


def save_contract(contract, data):
    contract = contract_name(contract)
    record = validate_contract(contract, data)
    request("POST", "contracts", params={"on_conflict": "contract"}, data=record)


def load_contract(contract):
    contract = contract_name(contract)
    rows = request("GET", "contracts", params={"select": "*", "contract": f"eq.{contract}"})
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError(f"Supabase 中缺少唯一的 {contract} 合约记录，请先运行 precision 更新")
    return validate_contract(contract, rows[0])
