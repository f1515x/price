"""Explicit dated execution specifications; evidence scope never implies other fields."""
from dataclasses import asdict

from trade_simulation import Config


def validate_periods(periods, start, end):
    previous = None
    multiplier = None
    for p in periods:
        if (type(p["start"]) is not int or type(p["end"]) is not int or p["start"] >= p["end"]
                or not isinstance(p["config"], Config) or not isinstance(p["source"],str) or not p["source"].strip()
                or not isinstance(p["verified_fields"],list)
                or any(k not in asdict(p["config"]) for k in p["verified_fields"])):
            raise ValueError("Invalid dated execution specification")
        if previous is not None and p["start"] != previous:
            raise ValueError("Execution periods overlap or contain a gap")
        if multiplier is not None and p["config"].multiplier != multiplier:
            raise ValueError("Multiplier changes require position conversion; unsupported")
        previous = p["end"]
        multiplier = p["config"].multiplier
    if not periods or periods[0]["start"] > start or periods[-1]["end"] < end:
        raise ValueError("Execution periods do not cover sample")


def at_time(periods, stamp):
    for p in periods:
        if p["start"] <= stamp < p["end"]:
            return p["config"]
    raise ValueError("Missing execution specification at timestamp")


def evidence(periods):
    return [dict(p,config=asdict(p["config"])) for p in periods]
