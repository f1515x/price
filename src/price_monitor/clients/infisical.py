"""Runtime-only Gate credentials via Infisical Universal Auth and Secrets v4."""
import os
from urllib.parse import urlsplit

import requests

from price_monitor.settings import load_env


CONFIG_KEYS = frozenset({
    "INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET", "INFISICAL_PROJECT_ID",
    "INFISICAL_ENV", "INFISICAL_ENVIRONMENT", "INFISICAL_URL", "INFISICAL_SECRET_PATH",
})


def _request(method, url, stage, **kwargs):
    try:
        response = requests.request(method, url, timeout=20, allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Infisical {stage}失败（HTTP {response.status_code}），请检查配置和权限")
        result = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError(f"Infisical {stage}失败，请检查连接、超时和返回格式") from None
    if not isinstance(result, dict):
        raise RuntimeError(f"Infisical {stage}返回格式无效")
    return result


def _clean(value, field):
    if not isinstance(value, str):
        raise RuntimeError(f"Infisical {field} 缺失或格式无效")
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        value = value[1:-1].strip()
    if not value or len(value) > 4096 or any(c in value for c in "\n\r\0"):
        raise RuntimeError(f"Infisical {field} 缺失或格式无效")
    return value


def load_credentials():
    # Read only integration configuration, never local Gate credentials.
    values = load_env(keys=CONFIG_KEYS)
    # Process environment takes precedence even when it uses the legacy alias.
    env_name = next((k for k in ("INFISICAL_ENV", "INFISICAL_ENVIRONMENT") if k in os.environ), None)
    environment = values.get(env_name) if env_name else values.get("INFISICAL_ENV", values.get("INFISICAL_ENVIRONMENT"))
    required = {
        "INFISICAL_CLIENT_ID": values.get("INFISICAL_CLIENT_ID"),
        "INFISICAL_CLIENT_SECRET": values.get("INFISICAL_CLIENT_SECRET"),
        "INFISICAL_PROJECT_ID": values.get("INFISICAL_PROJECT_ID"),
        "INFISICAL_ENV": environment,
    }
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"请配置 {name}")
        required[name] = value.strip()
    base_url = values.get("INFISICAL_URL", "").strip().rstrip("/") or "https://us.infisical.com"
    try:
        parsed = urlsplit(base_url)
        valid_url = parsed.scheme in ("http", "https") and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise RuntimeError("INFISICAL_URL 格式无效，请填写 Infisical 服务地址")
    path = values.get("INFISICAL_SECRET_PATH", "").strip() or "/"
    if not path.startswith("/"):
        raise RuntimeError("INFISICAL_SECRET_PATH 必须以 / 开头")
    auth = _request("POST", f"{base_url}/api/v1/auth/universal-auth/login", "认证",
                    json={"clientId": required["INFISICAL_CLIENT_ID"],
                          "clientSecret": required["INFISICAL_CLIENT_SECRET"]})
    token = auth.get("accessToken")
    if not isinstance(token, str) or not token.strip() or any(c in token for c in "\n\r\0"):
        raise RuntimeError("Infisical 认证未返回有效 Access Token")
    result = []
    for name in ("GATE_API_KEY", "GATE_API_SECRET"):
        data = _request("GET", f"{base_url}/api/v4/secrets/{name}", f"读取 {name}",
                        headers={"Authorization": "Bearer " + token.strip()},
                        params={"projectId": required["INFISICAL_PROJECT_ID"],
                                "environment": required["INFISICAL_ENV"], "secretPath": path,
                                "type": "shared"})
        secret = data.get("secret")
        if not isinstance(secret, dict) or secret.get("secretValueHidden"):
            raise RuntimeError(f"Infisical {name} 缺失或不可读取")
        result.append(_clean(secret.get("secretValue"), name))
    # Authenticate afresh each time; tokens and Gate secrets are never persisted.
    return tuple(result)
