"""
Curator Agent - 推荐策展（集成Kimi API）
"""
import os
from datetime import datetime
from typing import List, Dict, Any
from dataclasses import dataclass
import json

from .base_agent import BaseAgent
from .librarian import LibrarianAgent
from agents.scout import CandidateSong
from core.kimi_client import KimiClient


@dataclass
class Recommendation:
    """推荐项"""
    candidate: CandidateSong
    similarity_score: float
    match_reason: str
    action: str  # "highly_recommend" | "recommend" | "skip"


class CuratorAgent(BaseAgent):
    """
    策展人Agent - 集成LLM智能
    
    功能：
    - 计算候选歌曲与现有库的相似度
    - 调用Kimi API生成个性化推荐理由
    - 生成周报摘要
    """
    
    def __init__(self, config: Dict[str, Any], librarian: LibrarianAgent = None):
        super().__init__("Curator", config)
        self.config = config
        self.min_score = config.get("curator", {}).get("min_similarity_score", 0.6)
        self.librarian = librarian
        
        # 初始化Kimi客户端
        try:
            self.kimi = KimiClient()
            self.has_llm = True
            self.log("info", "Kimi API initialized")
        except ValueError as e:
            self.log("warning", f"Kimi API not available: {e}")
            self.kimi = None
            self.has_llm = False
        
        # 用户偏好（从库中分析）
        self.user_preferences = {
            "top_genres": [],
            "top_artists": [],
            "era_preference": None
        }
        
        # 缓存，减少重复API调用
        self._cache = {
            "artists": set(),  # 已查询过的艺术家
            "genres": set(),   # 已查询过的流派
            "queries": {}      # 查询结果缓存
        }
    
    def run(self, operation: str = "evaluate", **kwargs) -> Any:
        """
        执行策展操作
        """
        if operation == "evaluate":
            return self.evaluate_candidates(kwargs.get("candidates", []))
        
        elif operation == "report":
            return self.generate_weekly_report(kwargs.get("recommendations", []))
        
        elif operation == "analyze_preferences":
            return self._analyze_user_preferences()
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    def evaluate_candidates(self, candidates: List[CandidateSong]) -> List[Recommendation]:
        """
        评估候选歌曲，生成推荐列表
        """
        self.log("info", f"Evaluating {len(candidates)} candidates")
        
        # 分析用户偏好（用于LLM生成推荐理由）
        self._analyze_user_preferences()
        
        recommendations = []
        
        for candidate in candidates:
            # 计算相似度分数
            score = self._calculate_similarity(candidate)
            
            # 使用LLM生成推荐理由
            reason = self._generate_reason_with_llm(candidate)
            
            # 决定action
            if score >= 0.8:
                action = "highly_recommend"
            elif score >= self.min_score:
                action = "recommend"
            else:
                action = "skip"
            
            if action != "skip":
                rec = Recommendation(
                    candidate=candidate,
                    similarity_score=score,
                    match_reason=reason,
                    action=action
                )
                recommendations.append(rec)
        
        # 按分数排序
        recommendations.sort(key=lambda x: x.similarity_score, reverse=True)
        
        self.log("info", f"Generated {len(recommendations)} recommendations")
        return recommendations
    
    def generate_weekly_report(self, recommendations: List[Recommendation]) -> Dict:
        """生成周报（使用LLM生成摘要）"""
        self.log("info", "Generating weekly report with LLM")
        
        if not recommendations:
            return {
                "title": "本周音乐发现",
                "summary": "本周没有发现匹配的音乐",
                "recommendations": []
            }
        
        # 基础统计
        highly_recommended = [r for r in recommendations if r.action == "highly_recommend"]
        
        # 构造发现列表
        discoveries = [
            {
                "artist": r.candidate.artist,
                "title": r.candidate.title,
                "genre": r.candidate.genre_tags[0] if r.candidate.genre_tags else "未知"
            }
            for r in recommendations[:10]
        ]
        
        # 使用LLM生成摘要
        if self.has_llm:
            ai_summary = self.kimi.generate_weekly_summary(discoveries)
        else:
            ai_summary = f"本周发现{len(recommendations)}首推荐歌曲，其中包括{len(highly_recommended)}首强烈推荐。"
        
        # 按流派分组
        by_genre = {}
        for rec in recommendations:
            for tag in rec.candidate.genre_tags:
                if tag not in by_genre:
                    by_genre[tag] = []
                by_genre[tag].append(rec)
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "title": f"本周音乐发现 - {len(recommendations)}首推荐",
            "ai_summary": ai_summary,
            "summary": {
                "total_discovered": len(recommendations),
                "highly_recommended": len(highly_recommended),
                "genres": list(by_genre.keys()),
                "top_artists": list(set(r.candidate.artist for r in recommendations[:5]))
            },
            "recommendations": [
                {
                    "artist": r.candidate.artist,
                    "title": r.candidate.title,
                    "genre": r.candidate.genre_tags,
                    "score": round(r.similarity_score, 2),
                    "reason": r.match_reason,
                    "source": r.candidate.source
                }
                for r in recommendations[:10]
            ],
            "by_genre": {
                genre: [
                    {"artist": r.candidate.artist, "title": r.candidate.title}
                    for r in recs[:3]
                ]
                for genre, recs in by_genre.items()
            }
        }
        
        return report
    
    def _analyze_user_preferences(self) -> Dict:
        """
        分析用户音乐偏好（从本地库，带缓存）
        """
        if not self.librarian:
            return self.user_preferences
        
        # 如果已分析过，直接返回缓存
        if self.user_preferences.get("analyzed"):
            return self.user_preferences
        
        # 获取库的统计信息
        stats = self.librarian.get_stats()
        
        # 从统计中提取真实的偏好
        self.user_preferences["top_artists"] = [a[0] for a in stats.get("top_artists", [])[:5]]
        self.user_preferences["top_genres"] = [g[0] for g in stats.get("top_genres", [])[:5]]
        
        # 如果没有流派数据，尝试通过查询推断
        if not self.user_preferences["top_genres"]:
            sample_queries = ["摇滚", "流行", "说唱", "电子", "民谣", "爵士"]
            for genre in sample_queries:
                cache_key = f"pref:{genre}"
                if cache_key in self._cache["queries"]:
                    results = self._cache["queries"][cache_key]
                else:
                    results = self.librarian.query(genre, top_k=1)
                    self._cache["queries"][cache_key] = results
                
                if results:
                    self.user_preferences["top_genres"].append(genre)
        
        self.user_preferences["analyzed"] = True
        self.log("info", f"User preferences: artists={self.user_preferences['top_artists']}, genres={self.user_preferences['top_genres']}")
        return self.user_preferences
    
    def _calculate_similarity(self, candidate: CandidateSong) -> float:
        """计算候选歌曲与现有库的相似度（带缓存优化）"""
        scores = []
        
        # 1. 基于流派标签的相似度（缓存优化）
        if candidate.genre_tags and self.librarian:
            for tag in candidate.genre_tags:
                cache_key = f"genre:{tag}"
                if cache_key in self._cache["queries"]:
                    results = self._cache["queries"][cache_key]
                else:
                    results = self.librarian.query(cache_key, top_k=3)
                    self._cache["queries"][cache_key] = results
                
                if results:
                    avg_score = sum(r.get("similarity", 0) for r in results) / len(results)
                    scores.append(min(avg_score + 0.5, 1.0))
        
        # 2. 艺术家匹配（缓存优化）
        if self.librarian:
            artist = candidate.artist
            if artist in self._cache["artists"]:
                scores.append(0.95)  # 已有该艺术家
            else:
                cache_key = f"artist:{artist}"
                if cache_key in self._cache["queries"]:
                    artist_results = self._cache["queries"][cache_key]
                else:
                    artist_results = self.librarian.query(cache_key, top_k=1)
                    self._cache["queries"][cache_key] = artist_results
                
                if artist_results:
                    self._cache["artists"].add(artist)
                    scores.append(0.95)
        
        # 3. 基于元数据的启发式评分
        if candidate.metadata.get("upvote_ratio", 0) > 0.85:
            scores.append(0.4)
        
        if not scores:
            return 0.35  # 默认分数
        
        return min(sum(scores) / len(scores) + 0.1, 1.0)
    
    def _generate_reason_with_llm(self, candidate: CandidateSong) -> str:
        """
        使用LLM生成推荐理由
        """
        if not self.has_llm:
            return self._generate_reason_fallback(candidate)
        
        try:
            candidate_info = {
                "title": candidate.title,
                "artist": candidate.artist,
                "genre": candidate.genre_tags[0] if candidate.genre_tags else "未知",
                "album": candidate.metadata.get("album", "未知")
            }
            
            reason = self.kimi.generate_recommendation_reason(
                candidate_info,
                self.user_preferences
            )
            
            return reason
            
        except Exception as e:
            self.log("error", f"LLM generation failed: {e}")
            return self._generate_reason_fallback(candidate)
    
    def _generate_reason_fallback(self, candidate: CandidateSong) -> str:
        """Fallback推荐理由（无LLM时）"""
        reasons = []
        
        if candidate.genre_tags:
            genre = candidate.genre_tags[0]
            if genre in self.user_preferences.get("top_genres", []):
                reasons.append(f"属于你常听的{genre}风格")
            else:
                reasons.append(f"{genre}风格值得一试")
        
        if candidate.source == "reddit":
            reasons.append("来自音乐社区推荐")
        elif candidate.source == "rss":
            reasons.append("最新发行")
        
        return "；".join(reasons) if reasons else "根据你的口味推荐"
