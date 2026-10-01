"""Gate USDT perpetual current contract snapshots, not historical specifications."""
import argparse
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen

from kline import normalize_symbol

VERSION = "gate-contract-specs-v1"
ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/contracts/"
DOCS = "https://www.gate.com/docs/developers/apiv4/en/futures/"


def decimal_field(raw, key, positive=True):
    value = raw.get(key)
    if type(value) not in (str, int, float):
        raise ValueError("Invalid contract field: " + key)
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid contract field: " + key) from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("Invalid contract field: " + key)
    return number


def normalize(raw, symbol):
    symbol = normalize_symbol(symbol)
    if not isinstance(raw, dict) or raw.get("name") != symbol + "_USDT":
        raise ValueError("Contract identity mismatch")
    if raw.get("type") != "direct":
        raise ValueError("Only direct USDT contracts are supported")
    if type(raw.get("enable_decimal")) is not bool or type(raw.get("in_delisting")) is not bool:
        raise ValueError("Missing/invalid contract flags")
    numeric = {key: decimal_field(raw, key) for key in
               ("quanto_multiplier", "order_size_max", "order_price_round")}
    numeric["order_size_min"] = decimal_field(raw, "order_size_min", positive=False)
    if numeric["order_size_min"] < 0 or (not raw["enable_decimal"] and numeric["order_size_min"] == 0):
        raise ValueError("Invalid contract field: order_size_min")
    numeric.update({key: decimal_field(raw, key, positive=False) for key in
                    ("maker_fee_rate", "taker_fee_rate")})
    if numeric["order_size_max"] < numeric["order_size_min"]:
        raise ValueError("Maximum size is below minimum size")
    if not raw["enable_decimal"] and any(numeric[k] != numeric[k].to_integral_value()
                                         for k in ("order_size_min", "order_size_max")):
        raise ValueError("Integer contract has fractional size bounds")
    interval = raw.get("funding_interval")
    if type(interval) is not int or interval <= 0:
        raise ValueError("Invalid funding interval")
    # The decimal flag does not specify a quantity step. Never infer it from min size.
    step = None if raw["enable_decimal"] else "1"
    status = "UNSUPPORTED_DECIMAL_STEP" if step is None else "MAPPABLE_CURRENT_ASSUMPTION"
    if raw["in_delisting"] or raw.get("status") != "trading":
        status = "NOT_TRADING"
    return dict(symbol=symbol, contract=raw["name"], market="gate_usdt_perpetual",
                contract_type="direct", quantity_unit="contracts",
                multiplier=str(numeric["quanto_multiplier"]),
                min_quantity=str(numeric["order_size_min"]),
                max_quantity=str(numeric["order_size_max"]), quantity_step=step,
                price_tick=str(numeric["order_price_round"]),
                maker_fee_rate=str(numeric["maker_fee_rate"]),
                taker_fee_rate=str(numeric["taker_fee_rate"]),
                funding_interval_seconds=interval, status=status)


def request_contract(symbol):
    request = Request(ENDPOINT + normalize_symbol(symbol) + "_USDT",
                      headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def collect(symbols, destination, fetch=request_contract, clock=time.time):
    symbols = [normalize_symbol(s) for s in symbols]
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Provide unique symbols")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    blobs, records = {}, []
    for symbol in symbols:
        started = int(clock())
        body = fetch(symbol)
        received = int(clock())
        if received < started:
            raise ValueError("Clock moved backwards")
        raw = json.loads(body)
        spec = normalize(raw, symbol)
        name = symbol + "-raw.json"
        blobs[name] = body
        records.append(dict(spec, source_url=ENDPOINT + symbol + "_USDT",
                            requested_at=started, observed_at=received,
                            raw_file=name, raw_sha256=digest(body)))
    report = dict(version=VERSION, temporal_scope="CURRENT_SNAPSHOT_ONLY",
                  documentation=DOCS, source_sha256=digest(Path(__file__).read_bytes()),
                  contracts=records,
                  limitations=["No historical specification validity is established.",
                               "Published fees are not account-specific realized fees.",
                               "Funding interval is not a historical funding-rate series.",
                               "Simulation mapping only covers multiplier, min quantity and quantity step.",
                               "Price ticks and maximum order sizes require separate execution support."])
    destination.mkdir(parents=True, exist_ok=False)
    for name, body in blobs.items():
        (destination / name).write_bytes(body)
    (destination / "specs.json").write_bytes(encoded(report))
    return report


def load_snapshot(destination):
    destination = Path(destination)
    report = json.loads((destination / "specs.json").read_bytes())
    if report.get("version") != VERSION or report.get("temporal_scope") != "CURRENT_SNAPSHOT_ONLY":
        raise ValueError("Unsupported contract snapshot")
    if not report.get("contracts"):
        raise ValueError("Empty contract snapshot")
    seen = set()
    for record in report["contracts"]:
        symbol = normalize_symbol(record["symbol"])
        if symbol in seen or record["raw_file"] != symbol + "-raw.json":
            raise ValueError("Invalid snapshot identity")
        seen.add(symbol)
        body = (destination / record["raw_file"]).read_bytes()
        if digest(body) != record["raw_sha256"]:
            raise ValueError("Contract raw hash mismatch")
        spec = normalize(json.loads(body), symbol)
        if any(record.get(key) != value for key, value in spec.items()):
            raise ValueError("Contract normalized fields mismatch")
        if record["source_url"] != ENDPOINT + symbol + "_USDT":
            raise ValueError("Contract source mismatch")
        if any(type(record[k]) is not int or record[k] < 0 for k in ("requested_at", "observed_at")):
            raise ValueError("Invalid observation time")
        if record["observed_at"] < record["requested_at"]:
            raise ValueError("Invalid observation time")
    return report


def scenario_config(snapshot, symbol, base, *, assume_current_specs=False):
    """Explicit current-spec scenario only; preserves risk, fees and funding assumptions.

    The returned config uses contract counts, not base-asset units. This mapping
    does not add exchange tick/max-size enforcement to the daily simulator.
    """
    if assume_current_specs is not True:
        raise ValueError("Explicit assume_current_specs=True required; no historical validity")
    symbol = normalize_symbol(symbol)
    report = load_snapshot(snapshot)
    record = next((r for r in report["contracts"] if r["symbol"] == symbol), None)
    if record is None or record["status"] != "MAPPABLE_CURRENT_ASSUMPTION":
        raise ValueError("Contract is unavailable or unsupported")
    values = {k: float(record[k]) for k in ("multiplier", "quantity_step", "min_quantity")}
    if any(not math.isfinite(v) or v <= 0 for v in values.values()):
        raise ValueError("Contract values exceed simulation numeric range")
    return replace(base, **values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--output", required=True, help="New snapshot directory; never overwritten")
    args = parser.parse_args()
    report = collect(args.symbols, args.output)
    print(json.dumps(dict(temporal_scope=report["temporal_scope"],
                          contracts=[{k: r[k] for k in ("symbol", "multiplier", "min_quantity",
                                                       "quantity_step", "status")}
                                     for r in report["contracts"]]), indent=2))


if __name__ == "__main__":
    main()
