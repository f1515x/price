"""解析 reports/sizes.txt 并批量写入 Supabase，无需额外依赖。"""

import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SIZES_FILE = Path(__file__).resolve().parent / "reports" / "sizes.txt"
ORDER_FIELDS = {"contract", "activation_price", "side", "amount", "value"}


def parse_sizes(text):
    """完整校验报告后返回记录；数字字符串保留价格和价值的小数精度。"""
    records = []
    current = None
    timestamp = None
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line == "none":
            continue
        if timestamp is not None:
            raise ValueError(f"第 {line_number} 行：Timestamp 后存在多余内容")
        if line == "🚀 ====== Order Alert ======":
            if current is not None:
                raise ValueError(f"第 {line_number} 行：上一条订单缺少结束标记")
            current = {}
            continue
        if line == "======================":
            if current is None or set(current) != ORDER_FIELDS:
                missing = ORDER_FIELDS - set(current or {})
                raise ValueError(f"第 {line_number} 行：订单字段不完整：{', '.join(sorted(missing))}")
            records.append(current)
            current = None
            continue
        match = re.fullmatch(r"Timestamp:\s*(\d+)", line)
        if match:
            if current is not None or timestamp is not None:
                raise ValueError(f"第 {line_number} 行：Timestamp 位置错误或重复")
            timestamp = int(match[1])
            continue
        match = re.search(r"\b(contract|activation_price|side|amount|value)\s*:\s*(.+)$", line)
        if current is None or not match:
            raise ValueError(f"第 {line_number} 行：无法识别的报告内容：{line}")
        field, value = match.groups()
        if field in current:
            raise ValueError(f"第 {line_number} 行：重复字段 {field}")
        if field == "contract":
            if not re.fullmatch(r"[A-Z0-9_]+_USDT", value):
                raise ValueError(f"第 {line_number} 行：合约名称无效")
        elif field == "side":
            if value not in {"Open Long", "Open Short"}:
                raise ValueError(f"第 {line_number} 行：开仓方向无效")
        elif field == "amount":
            number = re.fullmatch(r"([+-]?\d+)\s+Contracts", value)
            if not number or int(number[1]) == 0:
                raise ValueError(f"第 {line_number} 行：张数必须为非零整数")
            value = int(number[1])
        else:
            unit = "USDT" if field == "activation_price" else "U"
            number = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+" + unit, value)
            if not number:
                raise ValueError(f"第 {line_number} 行：{field} 数值或单位无效")
            value = number[1]
            try:
                numeric = Decimal(value)
            except InvalidOperation:
                raise ValueError(f"第 {line_number} 行：{field} 数值无效") from None
            if not numeric.is_finite() or (field == "activation_price" and numeric <= 0):
                raise ValueError(f"第 {line_number} 行：{field} 数值无效")
        current[field] = value
    if current is not None:
        raise ValueError("报告末尾存在未完成的订单")
    for record in records:
        sign = 1 if record["side"] == "Open Long" else -1
        if record["amount"] * sign <= 0 or Decimal(record["value"]) * sign < 0:
            raise ValueError(f"{record['contract']} 的张数或价值符号与开仓方向不符")
        record["timestamp"] = timestamp
    return records


def load_config():
    values = {}
    path = Path(__file__).resolve().with_name(".env")
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


def request_json(url, key, *, data=None, token=None, minimal=False, method=None):
    method = method or ("GET" if data is None else "POST")
    headers = {"apikey": key, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    body = None
    if data is not None or method == "DELETE":
        headers["Prefer"] = "return=minimal" if minimal else "return=representation"
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers,
                      method=method)
    try:
        with urlopen(request, timeout=20) as response:
            content = response.read()
            return response.status, json.loads(content) if content else None
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if "42501" in detail:
            detail += ("\n数据库不允许当前身份读写这张表。请在 Supabase 配置表的读写权限，"
                       "或在本地 .env 的 SUPABASE_KEY 填入服务端密钥（secret key）。"
                       "不要把服务端密钥发到聊天或提交到 Git。")
        raise RuntimeError(f"Supabase HTTP {error.code}: {detail}") from None
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"网络请求失败: {error}") from None


def supabase(data=None, *, table=None, check_only=False, minimal=False):
    config = load_config()
    url = config.get("SUPABASE_URL", "").strip().rstrip("/")
    key = config.get("SUPABASE_KEY", "").strip()
    table = table or config.get("SUPABASE_TABLE", "orders").strip()
    if not url or not key:
        raise ValueError("请在脚本旁的 .env 中填写 SUPABASE_URL 和 SUPABASE_KEY")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/rest/v1)?", url):
        raise ValueError("SUPABASE_URL 请填写 https://<项目>.supabase.co，不要包含表名")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("表名只能包含字母、数字、下划线，不能以数字开头")
    if not check_only:
        if data is None:
            data = json.loads(config.get("SUPABASE_TEST_DATA", "{}"))
        if not isinstance(data, dict) and not (
            isinstance(data, list) and all(isinstance(row, dict) for row in data)
        ):
            raise ValueError("写入数据必须是 JSON 对象或对象数组")
        if data == []:
            print("Sizes 中没有订单，跳过写入。")
            return []
    endpoint = url + ("" if url.endswith("/rest/v1") else "/rest/v1") + "/" + table
    token = config.get("SUPABASE_ACCESS_TOKEN", "").strip() or None
    if check_only:
        status, _ = request_json(endpoint + "?select=*&limit=0", key, token=token)
        print(f"连接成功：{table}，HTTP {status}", flush=True)
        return None
    # 覆盖 contract 为空的历史记录及非空记录，清空整张目标表。
    status, _ = request_json(endpoint + "?or=(contract.is.null,contract.not.is.null)",
                             key, token=token, minimal=True, method="DELETE")
    print(f"旧数据清空成功：{table}，HTTP {status}")
    status, result = request_json(endpoint, key, data=data, token=token, minimal=minimal)
    count = len(data) if isinstance(data, list) else 1
    print(f"数据写入成功：{table}，{count} 条，HTTP {status}")
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", help="目标表，默认 orders")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sizes-file", type=Path, help="Sizes 报告路径，默认 reports/sizes.txt")
    group.add_argument("--data", help="显式写入 JSON 对象或对象数组")
    group.add_argument("--data-file", type=Path, help="保存记录的 JSON 文件")
    parser.add_argument("--check-only", action="store_true", help="只检查连接，不写入")
    parser.add_argument("--minimal", action="store_true", help="插入后不返回记录")
    parser.add_argument("--dry-run", action="store_true", help="解析并显示数据，不连接数据库")
    args = parser.parse_args(argv)
    if args.check_only and args.dry_run:
        parser.error("--check-only 和 --dry-run 不能同时使用")
    try:
        data = None
        if args.check_only:
            pass
        elif args.data is not None:
            data = json.loads(args.data)
        elif args.data_file is not None:
            data = json.loads(args.data_file.read_text(encoding="utf-8-sig"))
        else:
            data = parse_sizes((args.sizes_file or DEFAULT_SIZES_FILE).read_text(encoding="utf-8-sig"))
        if args.dry_run:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if data == []:
            print("Sizes 中没有订单，跳过写入。")
            return 0
        supabase(data, table=args.table, check_only=args.check_only, minimal=args.minimal)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
