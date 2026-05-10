from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .archiver import ValhallaArchiver
from .config import PROJECT_ROOT, Settings
from .cookie import mask_cookie_header, missing_required_cookies, parse_cookie_header, qq_gtk
from .exporter import export_run_files, latest_run_id
from .qq_api import QQAPIError, QQClient
from .storage import ArchiveStore, extract_groups


COOKIE_SNIPPET_PATH = PROJECT_ROOT / "tools" / "qq_cookie_snippet.js"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qq_valhalla", description="QQ 群管理数据本地采集归档工具")
    parser.add_argument("--env", type=Path, default=PROJECT_ROOT / ".env", help="环境变量文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查本地配置")
    doctor.add_argument("--live", action="store_true", help="实际请求群列表接口")

    snapshot = sub.add_parser("snapshot", help="执行一次归档")
    snapshot.add_argument("--group", action="append", default=[], help="只采集指定群号，可重复")
    snapshot.add_argument("--page-size", type=int, default=None, help="每页成员数")
    snapshot.add_argument("--max-pages", type=int, default=None, help="每个群最多采集页数，调试用")

    watch = sub.add_parser("watch", help="按间隔持续归档")
    watch.add_argument("--interval", type=int, default=None, help="轮询间隔秒数")
    watch.add_argument("--group", action="append", default=[], help="只采集指定群号，可重复")
    watch.add_argument("--page-size", type=int, default=None, help="每页成员数")
    watch.add_argument("--max-pages", type=int, default=None, help="每个群最多采集页数，调试用")

    dashboard = sub.add_parser("dashboard", help="重新生成最新归档的可视化页面")
    dashboard.add_argument("--run-id", type=int, default=None, help="指定 run_id，默认使用最新成功归档")

    sub.add_parser("cookie-snippet", help="输出浏览器 Console Cookie 复制脚本")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env(args.env)

    if args.command == "cookie-snippet":
        print(COOKIE_SNIPPET_PATH.read_text(encoding="utf-8"))
        return 0
    if args.command == "doctor":
        return command_doctor(settings, live=args.live)
    if args.command == "snapshot":
        return command_snapshot(settings, args.group, args.page_size, args.max_pages)
    if args.command == "watch":
        return command_watch(settings, args.group, args.interval, args.page_size, args.max_pages)
    if args.command == "dashboard":
        return command_dashboard(settings, args.run_id)
    parser.error("未知命令")
    return 2


def command_dashboard(settings: Settings, run_id: int | None) -> int:
    store = ArchiveStore(settings.db_path)
    try:
        target_run_id = run_id or latest_run_id(store)
        if target_run_id is None:
            print("没有可用于生成页面的成功归档。", file=sys.stderr)
            return 1
        exported = export_run_files(store, settings.archive_dir, target_run_id)
    finally:
        store.close()
    print(f"结构化 JSON：{exported['structured_json']}")
    print(f"可视化页面：{exported['dashboard']}")
    return 0


def command_doctor(settings: Settings, *, live: bool) -> int:
    cookies = parse_cookie_header(settings.cookie)
    missing = missing_required_cookies(cookies)
    config_ok = True
    print(f"数据库：{settings.db_path}")
    print(f"原始归档目录：{settings.archive_dir}")
    print(f"目标群：{', '.join(settings.group_ids) if settings.group_ids else '<未配置>'}")
    print(f"Cookie：{mask_cookie_header(settings.cookie) if settings.cookie else '<未配置>'}")
    if cookies.get("skey"):
        print(f"bkn：{qq_gtk(cookies['skey'])}")
    if missing:
        print(f"缺少必要 Cookie：{', '.join(missing)}", file=sys.stderr)
        config_ok = False
    if not settings.group_ids:
        print("缺少目标群配置：QQ_VALHALLA_GROUP_IDS", file=sys.stderr)
        config_ok = False
    if not config_ok:
        return 2
    print("必要 Cookie：已配置")
    print("目标群配置：已配置")
    if not live:
        return 0
    try:
        client = QQClient(
            settings.cookie,
            timeout=settings.timeout,
            user_agent=settings.user_agent,
            accept_language=settings.accept_language,
        )
        response = client.get_group_list()
        groups = extract_groups(response.data)
        found = {
            str(group.get("gc") or group.get("groupId") or group.get("group_id") or group.get("uin") or group.get("code"))
            for group in groups
        }
        matched = [group_id for group_id in settings.group_ids if group_id in found]
        missing_groups = [group_id for group_id in settings.group_ids if group_id not in found]
        print(f"群列表接口：OK，目标群匹配 {len(matched)}/{len(settings.group_ids)}")
        if missing_groups:
            print(f"未在群列表中找到：{', '.join(missing_groups)}", file=sys.stderr)
        return 0
    except QQAPIError as exc:
        print(f"群列表接口失败：{exc}", file=sys.stderr)
        return 1


def command_snapshot(settings: Settings, groups: list[str], page_size: int | None, max_pages: int | None) -> int:
    try:
        summary = run_snapshot(settings, groups, page_size, max_pages)
    except Exception as exc:
        print(f"归档失败：{exc}", file=sys.stderr)
        return 1
    print_summary(summary)
    return 0


def command_watch(
    settings: Settings,
    groups: list[str],
    interval: int | None,
    page_size: int | None,
    max_pages: int | None,
) -> int:
    seconds = interval or settings.poll_seconds
    print(f"开始轮询归档，间隔 {seconds} 秒。按 Ctrl+C 停止。")
    while True:
        try:
            summary = run_snapshot(settings, groups, page_size, max_pages)
            print_summary(summary)
        except KeyboardInterrupt:
            print("已停止。")
            return 0
        except Exception as exc:
            print(f"本轮归档失败：{exc}", file=sys.stderr)
            print("已停止轮询；请处理异常后重新启动 watch。", file=sys.stderr)
            return 1
        try:
            time.sleep(seconds)
        except KeyboardInterrupt:
            print("已停止。")
            return 0


def run_snapshot(settings: Settings, groups: list[str], page_size: int | None, max_pages: int | None):
    target_groups = groups or settings.group_ids
    if not target_groups:
        raise ValueError("未配置目标群号。请在 .env 设置 QQ_VALHALLA_GROUP_IDS，或使用 --group。")
    client = QQClient(
        settings.cookie,
        timeout=settings.timeout,
        user_agent=settings.user_agent,
        accept_language=settings.accept_language,
    )
    store = ArchiveStore(settings.db_path)
    try:
        archiver = ValhallaArchiver(client, store, settings.archive_dir)
        return archiver.snapshot(group_ids=target_groups, page_size=page_size or settings.page_size, max_pages=max_pages)
    finally:
        store.close()


def print_summary(summary) -> None:
    print(
        f"run={summary.run_id} 群列表={summary.groups_seen} "
        f"已采集群={summary.groups_crawled} 成员记录={summary.total_members_seen}"
    )
    for group in summary.group_summaries:
        print(
            f"- 群 {group.group_id}: 页={group.pages} 成员={group.members_seen} "
            f"新增={group.appeared} 变更={group.changed} 消失={group.disappeared}"
        )
    if summary.exports:
        print(f"结构化 JSON：{summary.exports.get('structured_json')}")
        print(f"可视化页面：{summary.exports.get('dashboard')}")
