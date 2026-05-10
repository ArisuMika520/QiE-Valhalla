from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .storage import ArchiveStore, clean_text


RETENTION_RUNS = 5


def pretty_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def group_avatar_url(group_id: str) -> str:
    return f"https://p.qlogo.cn/gh/{group_id}/{group_id}/100"


def member_avatar_url(uin: str) -> str:
    return f"https://q.qlogo.cn/g?b=qq&nk={uin}&s=100"


def role_label(value: Any) -> str:
    labels = {0: "群主", 1: "管理员", 2: "成员"}
    try:
        return labels.get(int(value), str(value))
    except (TypeError, ValueError):
        return ""


def gender_label(value: Any) -> str:
    labels = {0: "男", 1: "女", -1: "未知"}
    try:
        return labels.get(int(value), str(value))
    except (TypeError, ValueError):
        return ""


def timestamp_to_date(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    from datetime import datetime

    return datetime.fromtimestamp(number).strftime("%Y-%m-%d")


def latest_run_id(store: ArchiveStore) -> int | None:
    row = store.conn.execute(
        "SELECT id FROM archive_runs WHERE status='ok' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def build_run_payload(store: ArchiveStore, run_id: int) -> dict[str, Any]:
    run = store.conn.execute(
        "SELECT id, started_at, finished_at, status, metadata_json FROM archive_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise ValueError(f"找不到归档 run_id={run_id}")

    metadata = json.loads(run["metadata_json"] or "{}")
    raw_group_rows = store.conn.execute(
        """
        SELECT DISTINCT group_id
        FROM member_snapshots
        WHERE run_id=?
        ORDER BY group_id
        """,
        (run_id,),
    ).fetchall()
    group_ids: list[str] = []
    for group_id in metadata.get("group_ids", []):
        if str(group_id) not in group_ids:
            group_ids.append(str(group_id))
    for row in raw_group_rows:
        group_id = str(row["group_id"])
        if group_id not in group_ids:
            group_ids.append(group_id)

    groups: list[dict[str, Any]] = []
    for group_id in group_ids:
        group_row = store.conn.execute(
            "SELECT group_id, group_name, role_source, member_count, icon, raw_json, updated_at FROM groups WHERE group_id=?",
            (group_id,),
        ).fetchone()
        group_raw = json.loads(group_row["raw_json"]) if group_row and group_row["raw_json"] else {}
        group_name = clean_text(group_row["group_name"] if group_row else group_raw.get("gn", ""))
        member_rows = store.conn.execute(
            """
            SELECT uin, nick, card, role, gender, qage, join_time, last_speak_time,
                   point, raw_hash, raw_json, seen_at
            FROM member_snapshots
            WHERE run_id=? AND group_id=?
            ORDER BY role ASC, card COLLATE NOCASE, nick COLLATE NOCASE, uin
            """,
            (run_id, group_id),
        ).fetchall()
        members = [format_member(row) for row in member_rows]
        groups.append(
            {
                "group_id": group_id,
                "group_name": group_name,
                "avatar_url": group_avatar_url(group_id),
                "member_count_declared": group_row["member_count"] if group_row else None,
                "member_count_archived": len(members),
                "role_source": group_row["role_source"] if group_row else "",
                "updated_at": group_row["updated_at"] if group_row else "",
                "raw": group_raw,
                "members": members,
            }
        )

    return {
        "run": {
            "id": int(run["id"]),
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "status": run["status"],
            "metadata": json.loads(run["metadata_json"] or "{}"),
        },
        "latest_archive_time": run["finished_at"] or run["started_at"],
        "group_count": len(groups),
        "member_count": sum(len(group["members"]) for group in groups),
        "groups": groups,
    }


def format_member(row) -> dict[str, Any]:
    raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
    uin = str(row["uin"])
    level = raw.get("lv") if isinstance(raw.get("lv"), dict) else {}
    return {
        "uin": uin,
        "qq": uin,
        "avatar_url": member_avatar_url(uin),
        "nick": clean_text(row["nick"]),
        "card": clean_text(row["card"]),
        "display_name": clean_text(row["card"]) or clean_text(row["nick"]) or uin,
        "role": row["role"],
        "role_label": role_label(row["role"]),
        "gender": row["gender"],
        "gender_label": gender_label(row["gender"]),
        "qage": row["qage"],
        "join_time": row["join_time"],
        "join_date": timestamp_to_date(row["join_time"]),
        "last_speak_time": row["last_speak_time"],
        "last_speak_date": timestamp_to_date(row["last_speak_time"]),
        "point": row["point"],
        "level": level,
        "tags": raw.get("tags", []),
        "seen_at": row["seen_at"],
        "raw_hash": row["raw_hash"],
        "raw": raw,
    }


def export_run_files(store: ArchiveStore, archive_dir: Path, run_id: int) -> dict[str, Path]:
    payload = build_run_payload(store, run_id)
    day = (payload["latest_archive_time"] or "")[:10] or "unknown-date"
    day_dir = archive_dir / day
    day_dir.mkdir(parents=True, exist_ok=True)

    structured_path = day_dir / f"run_{run_id}.structured.json"
    structured_path.write_text(pretty_json_dumps(payload) + "\n", encoding="utf-8")

    dashboard_dir = archive_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    dashboard_path = dashboard_dir / "latest.html"
    dashboard_path.write_text(render_dashboard(payload), encoding="utf-8")
    (dashboard_dir / "latest.structured.json").write_text(pretty_json_dumps(payload) + "\n", encoding="utf-8")
    prune_export_files(archive_dir, keep=RETENTION_RUNS)
    return {"structured_json": structured_path, "dashboard": dashboard_path}


def write_error_marker(
    archive_dir: Path,
    *,
    run_id: int,
    error: str,
    metadata: dict[str, Any] | None = None,
    raw_responses: list[dict[str, Any]] | None = None,
) -> Path:
    day_dir = archive_dir / local_day()
    day_dir.mkdir(parents=True, exist_ok=True)
    marker_path = day_dir / f"run_{run_id}.error.json"
    payload = {
        "run_id": run_id,
        "status": "failed",
        "failed_at": local_now(),
        "error": error,
        "metadata": metadata or {},
        "raw_responses": raw_responses or [],
    }
    marker_path.write_text(pretty_json_dumps(payload) + "\n", encoding="utf-8")
    prune_export_files(archive_dir, keep=RETENTION_RUNS)
    return marker_path


def prune_export_files(archive_dir: Path, keep: int = RETENTION_RUNS) -> list[Path]:
    if keep < 1 or not archive_dir.exists():
        return []
    run_ids = sorted(
        {
            int(match.group(1))
            for file_path in archive_dir.glob("*/run_*.*")
            if (match := re.match(r"run_(\d+)\.", file_path.name))
        },
        reverse=True,
    )
    keep_ids = set(run_ids[:keep])
    removed: list[Path] = []
    for file_path in archive_dir.glob("*/run_*.*"):
        match = re.match(r"run_(\d+)\.", file_path.name)
        if not match:
            continue
        if int(match.group(1)) in keep_ids:
            continue
        file_path.unlink(missing_ok=True)
        removed.append(file_path)
    return removed


def local_now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def local_day() -> str:
    return local_now()[:10]


def render_dashboard(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QQ Valhalla 归档仪表盘</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #182033;
      --muted: #667085;
      --line: #e4e8f0;
      --blue: #1769e0;
      --green: #168a5b;
      --shadow: 0 14px 40px rgba(20, 31, 54, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      letter-spacing: 0;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.88);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    .wrap {{
      width: min(1180px, calc(100vw - 40px));
      margin: 0 auto;
    }}
    .top {{
      min-height: 74px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }}
    h1 {{
      font-size: 22px;
      margin: 0;
      font-weight: 720;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .pill {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 999px;
      padding: 7px 11px;
      white-space: nowrap;
    }}
    main {{ padding: 24px 0 40px; }}
    .toolbar {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
    }}
    .search {{
      width: 100%;
      height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 13px;
      font-size: 14px;
      outline: none;
      background: #fff;
    }}
    .search:focus {{ border-color: var(--blue); box-shadow: 0 0 0 3px rgba(23,105,224,.12); }}
    .group {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
      overflow: hidden;
    }}
    .group-head {{
      display: flex;
      gap: 16px;
      align-items: center;
      padding: 18px;
      border-bottom: 1px solid var(--line);
    }}
    .group-head img {{
      width: 64px;
      height: 64px;
      border-radius: 8px;
      background: #eef2f7;
      flex: 0 0 auto;
    }}
    .group-title {{
      min-width: 0;
      flex: 1;
    }}
    .group-title h2 {{
      margin: 0 0 7px;
      font-size: 18px;
      line-height: 1.25;
    }}
    .group-sub {{
      color: var(--muted);
      font-size: 13px;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .members {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
      padding: 16px;
    }}
    .member {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 12px;
      display: grid;
      grid-template-columns: 48px 1fr;
      gap: 12px;
      min-width: 0;
    }}
    .member img {{
      width: 48px;
      height: 48px;
      border-radius: 8px;
      background: #eef2f7;
    }}
    .name {{
      font-weight: 650;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }}
    .qq {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }}
    .facts {{
      grid-column: 1 / -1;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 4px;
    }}
    .fact {{
      font-size: 12px;
      color: #475467;
      background: #f2f5f9;
      border-radius: 999px;
      padding: 4px 8px;
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .empty {{
      color: var(--muted);
      padding: 30px 16px;
      text-align: center;
    }}
    @media (max-width: 760px) {{
      .wrap {{ width: min(100vw - 24px, 1180px); }}
      .top {{ align-items: flex-start; flex-direction: column; padding: 14px 0; gap: 10px; }}
      .meta {{ justify-content: flex-start; }}
      .toolbar {{ grid-template-columns: 1fr; }}
      .group-head {{ align-items: flex-start; }}
      .members {{ grid-template-columns: 1fr; padding: 12px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <h1>QQ Valhalla</h1>
      <div class="meta">
        <span class="pill">最新归档：<strong id="archive-time"></strong></span>
        <span class="pill">群：<strong id="group-count"></strong></span>
        <span class="pill">成员：<strong id="member-count"></strong></span>
      </div>
    </div>
  </header>
  <main class="wrap">
    <div class="toolbar">
      <input id="search" class="search" placeholder="搜索成员昵称、群昵称或 QQ 号">
      <div class="pill">Run <strong id="run-id"></strong></div>
    </div>
    <section id="groups"></section>
  </main>
  <script id="archive-data" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('archive-data').textContent);
    const groupsNode = document.getElementById('groups');
    const search = document.getElementById('search');
    document.getElementById('archive-time').textContent = data.latest_archive_time || '-';
    document.getElementById('group-count').textContent = data.group_count || 0;
    document.getElementById('member-count').textContent = data.member_count || 0;
    document.getElementById('run-id').textContent = data.run?.id ?? '-';

    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }}[ch]));
    }}
    function memberHtml(member) {{
      const facts = [
        member.role_label,
        member.gender_label,
        member.qage ? `Q龄 ${{member.qage}}` : '',
        member.join_date ? `入群 ${{member.join_date}}` : '',
        member.last_speak_date ? `发言 ${{member.last_speak_date}}` : '',
      ].filter(Boolean).map(item => `<span class="fact">${{esc(item)}}</span>`).join('');
      return `<article class="member" data-key="${{esc([member.display_name, member.nick, member.card, member.uin].join(' ').toLowerCase())}}">
        <img src="${{esc(member.avatar_url)}}" alt="">
        <div>
          <div class="name">${{esc(member.display_name)}}</div>
          <div class="qq">QQ：${{esc(member.uin)}}</div>
        </div>
        <div class="facts">${{facts}}</div>
      </article>`;
    }}
    function render() {{
      const keyword = search.value.trim().toLowerCase();
      const html = (data.groups || []).map(group => {{
        const members = (group.members || []).filter(member => {{
          if (!keyword) return true;
          return [member.display_name, member.nick, member.card, member.uin].join(' ').toLowerCase().includes(keyword);
        }});
        return `<section class="group">
          <div class="group-head">
            <img src="${{esc(group.avatar_url)}}" alt="">
            <div class="group-title">
              <h2>${{esc(group.group_name || group.group_id)}}</h2>
              <div class="group-sub">
                <span>群号：${{esc(group.group_id)}}</span>
                <span>成员归档：${{members.length}} / ${{group.member_count_archived}}</span>
              </div>
            </div>
          </div>
          <div class="members">${{members.length ? members.map(memberHtml).join('') : '<div class="empty">没有匹配成员</div>'}}</div>
        </section>`;
      }}).join('');
      groupsNode.innerHTML = html || '<div class="empty">暂无归档数据</div>';
    }}
    search.addEventListener('input', render);
    render();
  </script>
</body>
</html>
"""
