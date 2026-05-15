# -*- coding: utf-8 -*-
"""Scout 工具集 — 外部音乐发现"""
import json
from typing import Optional

from langchain_core.tools import tool


@tool
def discover_from_sources(source: str = "all") -> str:
    """从外部源发现新音乐。source 可选: 'all'(全部), 'rss'(RSS订阅), 'reddit'(Reddit), 'chinese'(中文源)。
    返回候选歌曲列表（JSON格式，含歌名、艺术家、来源、流派标签）。"""
    from agents.scout import ScoutAgent
    from graph.utils import load_config
    config = load_config()
    scout = ScoutAgent(config)
    candidates = scout.run(source=source)
    formatted = []
    for c in candidates:
        formatted.append({
            "title": c.title,
            "artist": c.artist,
            "source": c.source,
            "source_url": c.source_url,
            "genre_tags": c.genre_tags,
            "metadata": c.metadata,
        })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


@tool
def discover_similar_artist(artist: str, top_k: int = 8) -> str:
    """发现与指定艺术家风格相似的音乐。artist 为艺术家名，top_k 为返回数量。
    返回相似风格歌曲列表（JSON格式）。"""
    from agents.scout import ScoutAgent, DiscoveryRequest
    from graph.utils import load_config
    config = load_config()
    scout = ScoutAgent(config)
    request = DiscoveryRequest("similar_artist", {"artist": artist, "top_k": top_k}, f"与{artist}相似的歌曲")
    candidates = scout.run("active", discovery_request=request)
    formatted = []
    for c in candidates:
        formatted.append({
            "title": c.title,
            "artist": c.artist,
            "source": c.source,
            "reason": c.metadata.get("reason", ""),
        })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


@tool
def discover_by_mood(mood: str) -> str:
    """发现适合特定场景/情绪的音乐。mood 可选: 'work'(工作), 'study'(学习), 'workout'(运动),
    'relax'(放松), 'sleep'(睡眠), 'party'(派对), 'commute'(通勤)。
    返回推荐列表（JSON格式）。"""
    from agents.scout import ScoutAgent, DiscoveryRequest
    from graph.utils import load_config
    config = load_config()
    scout = ScoutAgent(config)
    request = DiscoveryRequest("mood", {"mood": mood}, f"适合{mood}场景")
    candidates = scout.run("active", discovery_request=request)
    formatted = []
    for c in candidates:
        formatted.append({
            "title": c.title,
            "artist": c.artist,
            "source": c.source,
        })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


@tool
def discover_artist_new(artist: str) -> str:
    """发现指定艺术家的最新发行（新专辑/新单曲）。artist 为艺术家名。
    返回最新发行列表（JSON格式）。"""
    from agents.scout import ScoutAgent, DiscoveryRequest
    from graph.utils import load_config
    config = load_config()
    scout = ScoutAgent(config)
    request = DiscoveryRequest("artist_new", {"artist": artist}, f"{artist}的最新歌曲")
    candidates = scout.run("active", discovery_request=request)
    formatted = []
    for c in candidates:
        formatted.append({
            "title": c.title,
            "artist": c.artist,
            "source": c.source,
        })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


SCOUT_TOOLS = [discover_from_sources, discover_similar_artist, discover_by_mood, discover_artist_new]
