"""Gate.io account and contract API boundary."""
import time
import hashlib
import hmac
import re
from price_monitor.settings import credentials

HOST = "https://api.gateio.ws"
PREFIX = "/api/v4"

def gen_sign(method, url, query_string=None, payload_string=None):
    """生成 Gate.io API 签名头"""
    API_KEY, API_SECRET = credentials()
    t = time.time()
    m = hashlib.sha512()
    m.update((payload_string or "").encode('utf-8'))
    hashed_payload = m.hexdigest()
    s = '%s\n%s\n%s\n%s\n%s' % (method, url, query_string or "", hashed_payload, t)
    sign = hmac.new(API_SECRET.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()
    return {'KEY': API_KEY, 'Timestamp': str(t), 'SIGN': sign}


def parse_max_leverage_from_q_multiplier(message):
    """
    从 q_multiplier 的输出中提取最大杠杆。

    支持字典或字符串输入，例如：
    {'leverage_max': '200'}

    为兼容原有调用，也支持 Gate 错误信息：
    limit [1, 100]
    """
    if message is None:
        return None

    if isinstance(message, dict):
        value = message.get('leverage_max')
    else:
        text = str(message)
        match = re.search(
            r"['\"]leverage_max['\"]\s*:\s*['\"]?([0-9]+(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
        if match:
            value = match.group(1)
        else:
            # 兼容原有的 LEVERAGE_EXCEEDED 返回值：limit [1, 100]
            match = re.search(
                r"\blimit\s*\[\s*[0-9]+(?:\.[0-9]+)?\s*,\s*"
                r"([0-9]+(?:\.[0-9]+)?)\s*\]",
                text,
                re.IGNORECASE,
            )
            if not match:
                return None
            value = match.group(1)

    try:
        leverage = float(value)
    except (TypeError, ValueError):
        return None

    if leverage <= 0 or not leverage.is_integer():
        return None
    return int(leverage)


def get_max_leverage(session, contract_name):
    """从公开合约信息接口读取合约允许的最大杠杆。"""
    url = f'/futures/usdt/contracts/{contract_name}'
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    resp = session.get(
        HOST + PREFIX + url,
        headers=headers,
        timeout=15,
    )

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"获取 {contract_name} 最大杠杆失败: "
            f"HTTP {resp.status_code} {resp.text}"
        ) from exc

    if not resp.ok:
        raise RuntimeError(
            f"获取 {contract_name} 最大杠杆失败: "
            f"HTTP {resp.status_code} {data}"
        )

    max_leverage = parse_max_leverage_from_q_multiplier(data)
    if max_leverage is None:
        raise RuntimeError(f"{contract_name} 的合约信息缺少 leverage_max: {data}")
    return max_leverage


def get_total_available_margin(session):
    """获取统一账户的可用保证金总额"""
    url = '/unified/accounts'
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    sign_headers = gen_sign('GET', PREFIX + url, '')
    headers.update(sign_headers)
    resp = session.get(HOST + PREFIX + url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return float(data.get('total_available_margin', 0.0))


