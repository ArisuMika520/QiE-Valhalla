from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(data: Any) -> str:
    return hashlib.sha256(json_dumps(data).encode("utf-8")).hexdigest()


def first_present(data: dict[str, Any], names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        value = data.get(name)
        if value not in (None, ""):
            return value
    return default


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return html.unescape(str(value).replace("&nbsp;", " ")).strip()


def extract_groups(response: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for source in ("create", "manage", "join", "groups", "data", "list"):
        value = response.get(source)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    copied = dict(item)
                    copied["_source"] = source
                    groups.append(copied)
    return groups


def normalize_group(raw: dict[str, Any]) -> dict[str, Any]:
    group_id = first_present(raw, ("gc", "groupId", "group_id", "uin", "code"))
    return {
        "group_id": str(group_id) if group_id is not None else "",
        "group_name": clean_text(first_present(raw, ("gn", "groupName", "group_name", "name"))),
        "role_source": str(raw.get("_source", "")),
        "member_count": first_present(raw, ("total", "memberCount", "member_count", "mem_num")),
        "icon": first_present(raw, ("icon", "avatar", "logo"), ""),
        "raw": raw,
    }


def extract_members(response: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("mems", "memberInfos", "members", "data", "list"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def response_total(response: dict[str, Any], fallback: int) -> int:
    for key in ("searchCount", "search_count", "total", "count"):
        value = response.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return fallback


def normalize_member(raw: dict[str, Any]) -> dict[str, Any]:
    uin = first_present(raw, ("uin", "u", "qq", "account"))
    card = clean_text(first_present(raw, ("card", "nickInGroup", "nick_in_group", "groupNick")))
    nick = clean_text(first_present(raw, ("nick", "nickname", "name")))
    level = raw.get("lv") if isinstance(raw.get("lv"), dict) else {}
    return {
        "uin": str(uin) if uin is not None else "",
        "nick": nick,
        "card": card,
        "role": first_present(raw, ("role", "groupRole")),
        "gender": first_present(raw, ("g", "gender", "sex")),
        "qage": first_present(raw, ("qage", "qAge")),
        "join_time": first_present(raw, ("joinTime", "join_time")),
        "last_speak_time": first_present(raw, ("lastSpeakTime", "last_speak_time")),
        "point": first_present(raw, ("point", "points"), level.get("point")),
        "raw": raw,
    }


@dataclass(frozen=True)
class SnapshotStats:
    inserted: int = 0
    changed: int = 0
    disappeared: int = 0


class ArchiveStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS archive_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS raw_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                endpoint TEXT NOT NULL,
                group_id TEXT,
                page_index INTEGER,
                fetched_at TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                response_sha256 TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES archive_runs(id)
            );
            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,
                group_name TEXT,
                role_source TEXT,
                member_count INTEGER,
                icon TEXT,
                raw_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS member_snapshots (
                run_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                uin TEXT NOT NULL,
                nick TEXT,
                card TEXT,
                role INTEGER,
                gender INTEGER,
                qage INTEGER,
                join_time INTEGER,
                last_speak_time INTEGER,
                point INTEGER,
                raw_hash TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY(run_id, group_id, uin),
                FOREIGN KEY(run_id) REFERENCES archive_runs(id)
            );
            CREATE TABLE IF NOT EXISTS latest_members (
                group_id TEXT NOT NULL,
                uin TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_run_id INTEGER NOT NULL,
                active INTEGER NOT NULL,
                raw_hash TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                PRIMARY KEY(group_id, uin)
            );
            CREATE TABLE IF NOT EXISTS member_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                uin TEXT NOT NULL,
                event_type TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                old_hash TEXT,
                new_hash TEXT,
                old_json TEXT,
                new_json TEXT,
                FOREIGN KEY(run_id) REFERENCES archive_runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_member_events_group_seen
                ON member_events(group_id, seen_at);
            """
        )
        self.conn.commit()

    def create_run(self, mode: str, metadata: dict[str, Any] | None = None) -> int:
        cursor = self.conn.execute(
            "INSERT INTO archive_runs(started_at, mode, status, metadata_json) VALUES(?,?,?,?)",
            (utc_now(), mode, "running", json_dumps(metadata or {})),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, error: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "UPDATE archive_runs SET finished_at=?, status=?, error=?, metadata_json=? WHERE id=?",
            (utc_now(), status, error, json_dumps(metadata or {}), run_id),
        )
        self.conn.commit()

    def save_raw_response(
        self,
        *,
        run_id: int,
        endpoint: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
        group_id: str | None = None,
        page_index: int | None = None,
    ) -> None:
        response_json = json_dumps(response_data)
        self.conn.execute(
            """
            INSERT INTO raw_responses(
                run_id, endpoint, group_id, page_index, fetched_at, request_json,
                response_json, response_sha256
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                endpoint,
                str(group_id) if group_id is not None else None,
                page_index,
                utc_now(),
                json_dumps(request_data),
                response_json,
                hashlib.sha256(response_json.encode("utf-8")).hexdigest(),
            ),
        )
        self.conn.commit()

    def raw_responses_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT endpoint, group_id, page_index, fetched_at, request_json, response_json, response_sha256
            FROM raw_responses
            WHERE run_id=?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "endpoint": row["endpoint"],
                "group_id": row["group_id"],
                "page_index": row["page_index"],
                "fetched_at": row["fetched_at"],
                "request": json.loads(row["request_json"]),
                "response": json.loads(row["response_json"]),
                "response_sha256": row["response_sha256"],
            }
            for row in rows
        ]

    def upsert_groups(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = [normalize_group(group) for group in groups]
        normalized = [group for group in normalized if group["group_id"]]
        now = utc_now()
        with self.conn:
            for group in normalized:
                self.conn.execute(
                    """
                    INSERT INTO groups(group_id, group_name, role_source, member_count, icon, raw_json, updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(group_id) DO UPDATE SET
                        group_name=excluded.group_name,
                        role_source=excluded.role_source,
                        member_count=excluded.member_count,
                        icon=excluded.icon,
                        raw_json=excluded.raw_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        group["group_id"],
                        group["group_name"],
                        group["role_source"],
                        group["member_count"],
                        group["icon"],
                        json_dumps(group["raw"]),
                        now,
                    ),
                )
        return normalized

    def save_member_page(
        self,
        *,
        run_id: int,
        group_id: str,
        members: list[dict[str, Any]],
    ) -> SnapshotStats:
        inserted = 0
        changed = 0
        now = utc_now()
        with self.conn:
            for raw_member in members:
                member = normalize_member(raw_member)
                if not member["uin"]:
                    continue
                member_hash = stable_hash(member["raw"])
                raw_json = json_dumps(member["raw"])
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO member_snapshots(
                        run_id, group_id, uin, nick, card, role, gender, qage,
                        join_time, last_speak_time, point, raw_hash, raw_json, seen_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        str(group_id),
                        member["uin"],
                        member["nick"],
                        member["card"],
                        member["role"],
                        member["gender"],
                        member["qage"],
                        member["join_time"],
                        member["last_speak_time"],
                        member["point"],
                        member_hash,
                        raw_json,
                        now,
                    ),
                )
                previous = self.conn.execute(
                    "SELECT raw_hash, raw_json, active FROM latest_members WHERE group_id=? AND uin=?",
                    (str(group_id), member["uin"]),
                ).fetchone()
                if previous is None:
                    inserted += 1
                    self._insert_event(run_id, str(group_id), member["uin"], "appeared", None, member_hash, None, raw_json, now)
                    self.conn.execute(
                        """
                        INSERT INTO latest_members(
                            group_id, uin, first_seen_at, last_seen_at, last_run_id,
                            active, raw_hash, raw_json
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (str(group_id), member["uin"], now, now, run_id, 1, member_hash, raw_json),
                    )
                else:
                    if previous["raw_hash"] != member_hash or int(previous["active"]) == 0:
                        changed += 1
                        event_type = "reappeared" if int(previous["active"]) == 0 else "changed"
                        self._insert_event(
                            run_id,
                            str(group_id),
                            member["uin"],
                            event_type,
                            previous["raw_hash"],
                            member_hash,
                            previous["raw_json"],
                            raw_json,
                            now,
                        )
                    self.conn.execute(
                        """
                        UPDATE latest_members
                        SET last_seen_at=?, last_run_id=?, active=1, raw_hash=?, raw_json=?
                        WHERE group_id=? AND uin=?
                        """,
                        (now, run_id, member_hash, raw_json, str(group_id), member["uin"]),
                    )
        return SnapshotStats(inserted=inserted, changed=changed)

    def mark_missing_members(self, *, run_id: int, group_id: str, seen_uins: set[str]) -> int:
        now = utc_now()
        disappeared = 0
        placeholders = ",".join("?" for _ in seen_uins)
        params: list[Any] = [str(group_id)]
        sql = "SELECT uin, raw_hash, raw_json FROM latest_members WHERE group_id=? AND active=1"
        if seen_uins:
            sql += f" AND uin NOT IN ({placeholders})"
            params.extend(sorted(seen_uins))
        rows = self.conn.execute(sql, params).fetchall()
        with self.conn:
            for row in rows:
                disappeared += 1
                self._insert_event(
                    run_id,
                    str(group_id),
                    row["uin"],
                    "disappeared",
                    row["raw_hash"],
                    None,
                    row["raw_json"],
                    None,
                    now,
                )
                self.conn.execute(
                    "UPDATE latest_members SET active=0, last_run_id=?, last_seen_at=? WHERE group_id=? AND uin=?",
                    (run_id, now, str(group_id), row["uin"]),
                )
        return disappeared

    def _insert_event(
        self,
        run_id: int,
        group_id: str,
        uin: str,
        event_type: str,
        old_hash: str | None,
        new_hash: str | None,
        old_json: str | None,
        new_json: str | None,
        seen_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO member_events(
                run_id, group_id, uin, event_type, seen_at,
                old_hash, new_hash, old_json, new_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (run_id, group_id, uin, event_type, seen_at, old_hash, new_hash, old_json, new_json),
        )
