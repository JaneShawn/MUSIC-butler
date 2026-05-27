# -*- coding: utf-8 -*-
"""Organizer 工具集 — 文件整理与去重"""
import json

from langchain_core.tools import tool


@tool
def organize_files(strategy: str = "artist/album", dry_run: bool = True) -> str:
    """整理音乐文件到规范目录结构。strategy 可选: 'artist/album'(默认), 'genre/artist',
    'year/artist', 'flat'(平铺), 'rename_only'(仅重命名)。
    设置 dry_run=True 仅预览不执行，dry_run=False 实际执行文件移动。
    返回整理计划或执行结果（JSON格式）。"""
    from graph.utils import load_config
    from agents.librarian import get_librarian
    from agents.organizer import OrganizerAgent, OrganizeStrategy
    librarian = get_librarian()
    organizer = OrganizerAgent(load_config(), librarian=librarian)

    strategy_enum = OrganizeStrategy.from_string(strategy)
    plan = organizer.run("plan", strategy=strategy_enum)

    if dry_run:
        preview = organizer.run("preview", plan=plan)
        return json.dumps({
            "mode": "preview",
            "total": preview.total if hasattr(preview, 'total') else len(plan) if isinstance(plan, list) else 0,
            "message": "预览模式：未实际移动文件。设置 dry_run=False 执行。",
            "plan_summary": str(preview)[:2000],
        }, ensure_ascii=False, indent=2)
    else:
        result = organizer.run("execute", plan=plan, dry_run=False)
        return json.dumps({
            "mode": "execute",
            "total": result.total,
            "executed": result.executed,
            "failed": result.failed,
            "conflicts": result.conflicts,
        }, ensure_ascii=False, indent=2)


@tool
def dedup_files(dry_run: bool = True) -> str:
    """检测并清理重复歌曲（基于艺术家+歌名判断）。dry_run=True 仅列出不删除。
    返回重复文件分组列表（JSON格式）。"""
    from graph.utils import load_config
    from agents.librarian import get_librarian
    from agents.organizer import OrganizerAgent
    librarian = get_librarian()
    organizer = OrganizerAgent(load_config(), librarian=librarian)
    duplicates = organizer._find_duplicates()

    formatted = {}
    for key, songs in duplicates.items():
        if len(songs) > 1:
            formatted[key] = [
                {"file_path": s.file_path, "artist": s.artist, "title": s.title}
                for s in songs
            ]

    return json.dumps({
        "duplicate_groups": len(formatted),
        "total_duplicate_files": sum(len(v) for v in formatted.values()),
        "dry_run": dry_run,
        "duplicates": formatted,
    }, ensure_ascii=False, indent=2)


@tool
def analyze_structure() -> str:
    """分析当前音乐库目录结构，返回统计数据（总歌曲、艺术家分布、流派分布、年代分布等）。
    用于理解库的组成。"""
    from graph.utils import load_config
    from agents.librarian import get_librarian
    from agents.organizer import OrganizerAgent
    librarian = get_librarian()
    organizer = OrganizerAgent(load_config(), librarian=librarian)
    analysis = organizer.run("analyze")
    return json.dumps(analysis, ensure_ascii=False, indent=2)


ORGANIZER_TOOLS = [organize_files, dedup_files, analyze_structure]
