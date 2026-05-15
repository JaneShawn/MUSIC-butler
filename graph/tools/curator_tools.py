# -*- coding: utf-8 -*-
"""Curator 工具集 — 推荐评估与周报"""
import json

from langchain_core.tools import tool


@tool
def evaluate_recommendations(discoveries_json: str) -> str:
    """评估候选歌曲并生成推荐。discoveries_json 是候选歌曲的 JSON 字符串。
    返回评估后的推荐列表（含分数、推荐理由、推荐等级）。"""
    from agents.scout import CandidateSong
    from agents.curator import CuratorAgent
    from datetime import datetime
    from graph.utils import load_config
    config = load_config()

    discoveries = json.loads(discoveries_json)
    candidates = []
    for d in discoveries:
        c = CandidateSong(
            title=d.get("title", ""),
            artist=d.get("artist", ""),
            source=d.get("source", "unknown"),
            source_url=d.get("source_url", ""),
            discovered_at=datetime.now(),
            genre_tags=d.get("genre_tags", []),
            metadata=d.get("metadata", {}),
        )
        candidates.append(c)

    curator = CuratorAgent(config)
    recs = curator.run("evaluate", candidates=candidates)
    formatted = []
    for r in recs:
        formatted.append({
            "title": r.candidate.title,
            "artist": r.candidate.artist,
            "score": round(r.similarity_score, 2),
            "reason": r.match_reason,
            "action": r.action,
            "source": r.candidate.source,
        })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


@tool
def generate_weekly_report() -> str:
    """生成本周音乐发现周报。汇总最近发现的歌曲、评估推荐、生成摘要。
    返回周报（JSON格式，含标题、摘要、推荐列表）。"""
    from agents.scout import ScoutAgent
    from agents.curator import CuratorAgent
    from graph.utils import load_config
    config = load_config()

    scout = ScoutAgent(config)
    candidates = scout.run(source="all")
    if not candidates:
        return json.dumps({"message": "本周没有发现新音乐"}, ensure_ascii=False)

    curator = CuratorAgent(config)
    recs = curator.run("evaluate", candidates=candidates)
    report = curator.run("report", recommendations=recs)

    return json.dumps({
        "title": report.get("title", ""),
        "ai_summary": report.get("ai_summary", ""),
        "summary": report.get("summary", {}),
        "recommendations": report.get("recommendations", [])[:10],
    }, ensure_ascii=False, indent=2)


CURATOR_TOOLS = [evaluate_recommendations, generate_weekly_report]
