"""Strict shared JSON parameters for offline collection and simulation."""
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
from pathlib import Path

from event_study import Config as EventConfig
from indicators import Config as IndicatorConfig
from structure_history import Config as StructureConfig
from trade_simulation import Config as ExecutionConfig


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration key: " + key)
        result[key] = value
    return result


def _section(cls, value):
    if not isinstance(value, dict):
        raise ValueError(cls.__module__ + " parameters must be an object")
    known = {f.name: f.type for f in fields(cls)}
    if value.keys() - known.keys():
        raise ValueError("Unknown parameters: " + str(sorted(value.keys() - known.keys())))
    for key, number in value.items():
        expected = known[key]
        if (type(number) not in (int, float) or not math.isfinite(number)
                or (expected is int and type(number) is not int)):
            raise ValueError("Invalid numeric parameter: " + key)
    try:
        return cls(**value)
    except (TypeError, OverflowError) as exc:
        raise ValueError("Missing or invalid " + cls.__module__ + " parameters") from exc


@dataclass(frozen=True)
class Profile:
    collection: dict
    indicators: IndicatorConfig
    structures: StructureConfig
    events: EventConfig
    execution: ExecutionConfig
    evidence: dict

    def collector(self):
        from candidate_store import Config as CandidateConfig
        from collection_scheduler import Config
        return Config(**self.collection, indicators=self.indicators, structures=self.structures,
                      candidates=CandidateConfig(self.events.tail, self.events.move, self.events.stretch),
                      parameter_profile=self.evidence)


def load_profile(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object,
                       parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + v)))
    keys = {"schema_version", "collection", "indicators", "structures", "events", "execution"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Expected exactly the shared research configuration sections")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported research configuration schema")
    collection = value["collection"]
    if not isinstance(collection, dict) or set(collection) != {"symbols", "start", "close_delay"}:
        raise ValueError("Expected collection symbols, start and close_delay")
    if (not isinstance(collection["symbols"], list)
            or any(not isinstance(s, str) or not s.strip() for s in collection["symbols"])
            or not isinstance(collection["start"], str)):
        raise ValueError("Expected symbol list and UTC start date")
    from collection_scheduler import Config
    from history import date_timestamp
    collection = dict(collection, start=date_timestamp(collection["start"]))
    normalized = Config(**collection)
    collection["symbols"] = normalized.symbols
    indicators = _section(IndicatorConfig, value["indicators"])
    structures = _section(StructureConfig, value["structures"])
    events = _section(EventConfig, value["events"])
    execution = _section(ExecutionConfig, value["execution"])
    parameters = dict(schema_version=1, collection=collection, indicators=asdict(indicators),
                      structures=asdict(structures), events=asdict(events), execution=asdict(execution))
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
    evidence = dict(schema_version=1, file_sha256=hashlib.sha256(raw).hexdigest(),
                    parameter_version=hashlib.sha256(canonical.encode()).hexdigest(), parameters=json.loads(canonical))
    return Profile(collection, indicators, structures, events, execution, evidence)
