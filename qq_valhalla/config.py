from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def parse_group_ids(value: str) -> list[str]:
    seen: set[str] = set()
    group_ids: list[str] = []
    for item in re.split(r"[,;\s]+", value or ""):
        group_id = item.strip()
        if not group_id or group_id in seen:
            continue
        seen.add(group_id)
        group_ids.append(group_id)
    return group_ids


@dataclass(frozen=True)
class Settings:
    cookie: str
    group_ids: list[str]
    db_path: Path
    archive_dir: Path
    timeout: float
    page_size: int
    poll_seconds: int
    user_agent: str
    accept_language: str

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_env_file(env_file or PROJECT_ROOT / ".env")
        return cls(
            cookie=os.environ.get("QQ_VALHALLA_COOKIE", ""),
            group_ids=parse_group_ids(os.environ.get("QQ_VALHALLA_GROUP_IDS", "")),
            db_path=PROJECT_ROOT / os.environ.get("QQ_VALHALLA_DB", "data/valhalla.sqlite3"),
            archive_dir=PROJECT_ROOT / os.environ.get("QQ_VALHALLA_ARCHIVE_DIR", "archive"),
            timeout=float(os.environ.get("QQ_VALHALLA_TIMEOUT", "15")),
            page_size=int(os.environ.get("QQ_VALHALLA_PAGE_SIZE", "40")),
            poll_seconds=int(os.environ.get("QQ_VALHALLA_POLL_SECONDS", "300")),
            user_agent=os.environ.get(
                "QQ_VALHALLA_USER_AGENT",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            ),
            accept_language=os.environ.get("QQ_VALHALLA_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9"),
        )
