from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exporter import export_run_files, pretty_json_dumps, write_error_marker
from .qq_api import QQClient
from .storage import ArchiveStore, extract_groups, extract_members, response_total, utc_now


GROUP_LIST_KEYS = ("create", "manage", "join", "groups", "data", "list")
MAX_MEMBER_PAGE_SIZE = 40


@dataclass
class GroupSummary:
    group_id: str
    pages: int = 0
    members_seen: int = 0
    appeared: int = 0
    changed: int = 0
    disappeared: int = 0


@dataclass
class SnapshotSummary:
    run_id: int
    groups_seen: int = 0
    groups_crawled: int = 0
    total_members_seen: int = 0
    group_summaries: list[GroupSummary] = field(default_factory=list)
    exports: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "groups_seen": self.groups_seen,
            "groups_crawled": self.groups_crawled,
            "total_members_seen": self.total_members_seen,
            "group_summaries": [summary.__dict__ for summary in self.group_summaries],
            "exports": self.exports,
        }


class ValhallaArchiver:
    def __init__(self, client: QQClient, store: ArchiveStore, archive_dir: Path) -> None:
        self.client = client
        self.store = store
        self.archive_dir = archive_dir

    def snapshot(
        self,
        *,
        group_ids: list[str] | None = None,
        page_size: int = MAX_MEMBER_PAGE_SIZE,
        max_pages: int | None = None,
    ) -> SnapshotSummary:
        target_group_ids = [str(group_id) for group_id in group_ids or [] if str(group_id).strip()]
        if not target_group_ids:
            raise ValueError("未配置目标群号。请在 .env 设置 QQ_VALHALLA_GROUP_IDS。")
        effective_page_size = normalize_member_page_size(page_size)
        run_id = self.store.create_run("snapshot", {"page_size": effective_page_size, "group_ids": target_group_ids})
        summary = SnapshotSummary(run_id=run_id)
        try:
            groups_response = self.client.get_group_list()
            validate_group_list_response(groups_response.data)
            filtered_group_data = filter_group_list_response(groups_response.data, set(target_group_ids))
            self._record_raw(run_id, groups_response.endpoint, groups_response.request_data, filtered_group_data)
            groups = self.store.upsert_groups(extract_groups(filtered_group_data))
            summary.groups_seen = len(groups)
            validate_target_groups_found(target_group_ids, groups)

            for group_id in target_group_ids:
                group_summary = self._snapshot_group(run_id, str(group_id), effective_page_size, max_pages)
                summary.groups_crawled += 1
                summary.total_members_seen += group_summary.members_seen
                summary.group_summaries.append(group_summary)

            self.store.finish_run(run_id, "ok", metadata=summary.as_dict())
            exported = export_run_files(self.store, self.archive_dir, run_id)
            summary.exports = {name: str(path) for name, path in exported.items()}
            self.store.finish_run(run_id, "ok", metadata=summary.as_dict())
            return summary
        except Exception as exc:
            error_marker = write_error_marker(
                self.archive_dir,
                run_id=run_id,
                error=str(exc),
                metadata=summary.as_dict(),
                raw_responses=self.store.raw_responses_for_run(run_id),
            )
            summary.exports["error_marker"] = str(error_marker)
            self.store.finish_run(run_id, "failed", error=str(exc), metadata=summary.as_dict())
            raise

    def _snapshot_group(self, run_id: int, group_id: str, page_size: int, max_pages: int | None) -> GroupSummary:
        summary = GroupSummary(group_id=group_id)
        seen_uins: set[str] = set()
        page_index = 1
        while True:
            start = (page_index - 1) * page_size
            end = start + page_size - 1
            response = self.client.search_group_members(group_id, start, end)
            self._record_raw(run_id, response.endpoint, response.request_data, response.data, group_id=group_id, page_index=page_index)
            validate_member_response(response.data, group_id=group_id, start=start, end=end)
            members = extract_members(response.data)
            for member in members:
                uin = member.get("uin")
                if uin not in (None, ""):
                    seen_uins.add(str(uin))
            stats = self.store.save_member_page(run_id=run_id, group_id=group_id, members=members)
            total = response_total(response.data, fallback=len(members))
            summary.pages += 1
            summary.members_seen += len(members)
            summary.appeared += stats.inserted
            summary.changed += stats.changed

            if not members:
                break
            if max_pages is not None and page_index >= max_pages:
                break
            if start + len(members) >= total:
                break
            page_index += 1

        summary.disappeared = self.store.mark_missing_members(run_id=run_id, group_id=group_id, seen_uins=seen_uins)
        if summary.members_seen == 0:
            raise ValueError(f"群 {group_id} 的成员结果为 0，停止归档。请检查 Cookie、权限或接口响应。")
        return summary

    def _record_raw(
        self,
        run_id: int,
        endpoint: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
        *,
        group_id: str | None = None,
        page_index: int | None = None,
    ) -> None:
        self.store.save_raw_response(
            run_id=run_id,
            endpoint=endpoint,
            request_data=request_data,
            response_data=response_data,
            group_id=group_id,
            page_index=page_index,
        )
        day_dir = self.archive_dir / utc_now()[:10]
        day_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": run_id,
            "fetched_at": utc_now(),
            "endpoint": endpoint,
            "group_id": group_id,
            "page_index": page_index,
            "request": request_data,
            "response": response_data,
        }
        with (day_dir / f"run_{run_id}.jsonl").open("a", encoding="utf-8") as file:
            file.write(pretty_json_dumps(record) + "\n")


def filter_group_list_response(response_data: dict[str, Any], target_group_ids: set[str]) -> dict[str, Any]:
    """只保留指定群的群列表响应，避免把非目标群信息写入归档。"""
    filtered: dict[str, Any] = {}
    for key, value in response_data.items():
        if key in GROUP_LIST_KEYS and isinstance(value, list):
            filtered[key] = [
                item
                for item in value
                if isinstance(item, dict) and _group_id_from_item(item) in target_group_ids
            ]
        else:
            filtered[key] = value
    return filtered


def validate_group_list_response(response_data: dict[str, Any]) -> None:
    if not isinstance(response_data, dict):
        raise ValueError("群列表接口返回不是 JSON object，停止归档。")
    if response_data.get("ec") == 0 and response_data.get("errcode") == 0:
        if any(isinstance(response_data.get(key), list) for key in GROUP_LIST_KEYS):
            return
        raise ValueError("群列表接口返回成功但没有群列表字段，停止归档。")


def validate_target_groups_found(target_group_ids: list[str], groups: list[dict[str, Any]]) -> None:
    found = {str(group["group_id"]) for group in groups if group.get("group_id")}
    missing = [group_id for group_id in target_group_ids if group_id not in found]
    if missing:
        raise ValueError(f"目标群未在群列表中找到：{', '.join(missing)}。停止归档。")


def _group_id_from_item(item: dict[str, Any]) -> str:
    for key in ("gc", "groupId", "group_id", "uin", "code"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def normalize_member_page_size(page_size: int) -> int:
    if page_size < 1:
        return 1
    return min(page_size, MAX_MEMBER_PAGE_SIZE)


def validate_member_response(response_data: dict[str, Any], *, group_id: str, start: int, end: int) -> None:
    """识别 qun_mgr 成员接口的空壳响应，避免静默归档 0 成员。"""
    if any(key in response_data for key in ("mems", "search_count", "count", "max_count")):
        return
    if response_data.get("ec") == 0 and response_data.get("errcode") == 0:
        raise ValueError(
            "成员接口返回空壳响应，未包含 mems/search_count。"
            f"group_id={group_id}, st={start}, end={end}。"
            f"请确认页大小不超过 {MAX_MEMBER_PAGE_SIZE}，并重新运行。"
        )
