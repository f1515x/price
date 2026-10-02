"""Shared paths and explicit credential loading without import side effects."""
import os
from pathlib import Path


def _project_root():
    override = os.environ.get("PRICE_MONITOR_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


ROOT_DIR = _project_root()
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"


def load_env():
    """Read optional root .env, then apply process environment overrides."""
    values = {}
    path = ROOT_DIR / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


def credentials():
    values = load_env()
    key = values.get("API_KEY", "").strip()
    secret = values.get("API_SECRET", "").strip()
    if not key or not secret:
        raise RuntimeError("账户接口需要 API_KEY 和 API_SECRET：请设置环境变量或根目录 .env")
    return key, secret
