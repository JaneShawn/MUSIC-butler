"""
Scout Agent - 外部音乐发现
"""
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import requests
import feedparser

from .base_agent import BaseAgent
from core.metadata_fetcher import MetadataFetcher


@dataclass
class CandidateSong:
    """候选歌曲"""
    title: str
    artist: str
    source: str  # 来源
    source_url: str
    discovered_at: datetime
    genre_tags: List[str]
    metadata: Dict[str, Any]


@dataclass
class DiscoveryRequest:
    """主动发现请求"""
    mode: str  # similar_artist|mood|playlist|artist_new|explore
    params: Dict[str, Any]
    reason: str  # 发现原因/描述
    

def extract_baidu_link(text: str) -> Optional[Dict]:
    """从文本中提取百度网盘链接"""
    # 匹配 pan.baidu.com/s/xxx 和提取码
    link_pattern = r'https?://pan\.baidu\.com/s/([a-zA-Z0-9_-]+)'
    code_pattern = r'提取码[：:]?\s*([a-zA-Z0-9]{4})'
    
    link_match = re.search(link_pattern, text)
    code_match = re.search(code_pattern, text)
    
    if link_match:
        return {
            "url": f"https://pan.baidu.com/s/{link_match.group(1)}",
            "code": code_match.group(1) if code_match else None
        }
    return None


class ScoutAgent(BaseAgent):
    """
    侦察兵Agent
    - 监控RSS源
    - 监控Reddit音乐社区
    - 监控音乐API新发行
    - 提取网盘链接（备用）
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("Scout", config)
        self.config = config
        
        # 数据源配置
        self.rss_feeds = config.get("scout", {}).get("rss_feeds", [])
        self.reddit_subs = config.get("scout", {}).get("reddit_subs", [])
        self.max_candidates = config.get("scout", {}).get("max_candidates_per_run", 20)
        
        # 元数据查询
        self.metadata_fetcher = MetadataFetcher(config)
        
        # 已发现的歌曲去重
        self.discovered_ids: set = set()
        
    def run(self, source: str = "all", **kwargs) -> List[CandidateSong]:
        """
        运行发现任务
        
        Args:
            source: all|rss|reddit|api|active
            **kwargs: 额外参数，用于主动发现模式
        """
        self.log("info", f"Starting discovery from: {source}")
        
        candidates = []
        
        if source in ["all", "rss"]:
            candidates.extend(self._check_rss())
        
        if source in ["all", "reddit"]:
            candidates.extend(self._check_reddit())
        
        if source in ["all", "chinese"]:
            candidates.extend(self._check_chinese_sources())
        
        # 主动发现模式
        if source == "active" or kwargs.get("discovery_request"):
            request = kwargs.get("discovery_request")
            if request:
                candidates.extend(self._active_discovery(request))
        
        # 去重
        unique_candidates = []
        for c in candidates:
            song_id = f"{c.artist}-{c.title}"
            if song_id not in self.discovered_ids:
                self.discovered_ids.add(song_id)
                unique_candidates.append(c)
        
        # 限制数量
        result = unique_candidates[:self.max_candidates]
        self.log("info", f"Discovered {len(result)} new candidates")
        
        return result
    
    def _check_rss(self) -> List[CandidateSong]:
        """检查RSS源"""
        candidates = []
        
        for feed_url in self.rss_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:10]:  # 只检查最新的10条
                    # 尝试解析歌曲信息
                    song_info = self._parse_song_from_text(
                        f"{entry.get('title', '')} {entry.get('summary', '')}"
                    )
                    
                    if song_info:
                        candidate = CandidateSong(
                            title=song_info["title"],
                            artist=song_info["artist"],
                            source="rss",
                            source_url=entry.get("link", ""),
                            discovered_at=datetime.now(),
                            genre_tags=song_info.get("tags", []),
                            metadata={
                                "published": entry.get("published", ""),
                                "links": extract_baidu_link(entry.get("summary", ""))
                            }
                        )
                        candidates.append(candidate)
                        
            except Exception as e:
                self.log("error", f"RSS check failed for {feed_url}: {e}")
        
        # 如果RSS没有结果，尝试内置的中文音乐源
        if not candidates:
            candidates.extend(self._check_chinese_sources())
        
        return candidates
    
    def _check_chinese_sources(self) -> List[CandidateSong]:
        """检查中文音乐源（内置备用）"""
        candidates = []
        
        # 网易云新歌榜
        try:
            url = "https://music.163.com/api/playlist/detail?id=3779629"  # 新歌榜
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://music.163.com/"
            }
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('result') and data['result'].get('tracks'):
                    for track in data['result']['tracks'][:5]:  # 取前5首
                        candidate = CandidateSong(
                            title=track.get('name', ''),
                            artist=', '.join([a.get('name', '') for a in track.get('artists', [])]),
                            source="netease_new",
                            source_url=f"https://music.163.com/song?id={track.get('id')}",
                            discovered_at=datetime.now(),
                            genre_tags=[],
                            metadata={
                                "album": track.get('album', {}).get('name', ''),
                                "popularity": track.get('popularity', 0)
                            }
                        )
                        candidates.append(candidate)
        except Exception as e:
            self.log("error", f"NetEase check failed: {e}")
        
        return candidates
    
    def _check_reddit(self) -> List[CandidateSong]:
        """检查Reddit音乐社区（可选，需要praw）"""
        candidates = []
        
        # 检查是否有praw模块
        try:
            import praw
        except ImportError:
            self.log("info", "Reddit support disabled (praw not installed). Use: pip install praw")
            return candidates
        
        # 检查环境变量
        if not os.getenv("REDDIT_CLIENT_ID") or not os.getenv("REDDIT_CLIENT_SECRET"):
            self.log("info", "Reddit API keys not configured (set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)")
            return candidates
        
        try:
            reddit = praw.Reddit(
                client_id=os.getenv("REDDIT_CLIENT_ID"),
                client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
                user_agent=os.getenv("REDDIT_USER_AGENT", "MusicAgent/1.0")
            )
            
            for sub_name in self.reddit_subs:
                subreddit = reddit.subreddit(sub_name)
                
                # 获取热门帖子
                for post in subreddit.hot(limit=10):
                    # 解析帖子标题
                    song_info = self._parse_song_from_text(post.title)
                    
                    if song_info:
                        # 查询更详细的元数据
                        full_meta = self.metadata_fetcher.query_by_name(
                            song_info["artist"], 
                            song_info["title"]
                        )
                        
                        candidate = CandidateSong(
                            title=song_info["title"],
                            artist=song_info["artist"],
                            source=f"reddit/r/{sub_name}",
                            source_url=f"https://reddit.com{post.permalink}",
                            discovered_at=datetime.now(),
                            genre_tags=full_meta.get("genres", song_info.get("tags", [])),
                            metadata={
                                "score": post.score,
                                "upvote_ratio": post.upvote_ratio,
                                "links": extract_baidu_link(post.selftext)
                            }
                        )
                        candidates.append(candidate)
                        
        except Exception as e:
            self.log("error", f"Reddit check failed: {e}")
        
        return candidates
    
    def _parse_song_from_text(self, text: str) -> Optional[Dict]:
        """
        从文本中解析歌曲信息
        简单实现：匹配 "Artist - Title" 格式
        """
        # 常见的歌曲标题格式
        patterns = [
            r'([^-]+)\s+-\s+(.+?)(?:\s*[\(\[]|$)',  # Artist - Title
            r'(.+?)\s+by\s+(.+?)(?:\s*[\(\[]|$)',   # Title by Artist
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                artist = match.group(1).strip()
                title = match.group(2).strip()
                
                # 简单的清理
                artist = re.sub(r'\[.*?\]|\(.*?\)', '', artist).strip()
                title = re.sub(r'\[.*?\]|\(.*?\)', '', title).strip()
                
                if len(artist) > 1 and len(title) > 1:
                    return {
                        "artist": artist,
                        "title": title,
                        "tags": []
                    }
        
        return None

    
    # ==================== 主动发现模式 ====================
    
    def _active_discovery(self, request: DiscoveryRequest) -> List[CandidateSong]:
        """
        主动发现 - 根据用户请求智能发现
        
        模式：
        - similar_artist: 发现相似艺术家
        - mood: 根据心情/场景发现  
        - artist_new: 追踪特定艺术家新发行
        - explore: 探索小众/冷门音乐
        """
        mode = request.mode
        params = request.params
        
        self.log("info", f"Active discovery: {mode} with params {params}")
        
        if mode == "similar_artist":
            return self._discover_similar_artists(params.get("artist"), params.get("top_k", 5))
        
        elif mode == "mood":
            return self._discover_by_mood(params.get("mood"))
        
        elif mode == "artist_new":
            return self._discover_artist_new(params.get("artist"))
        
        elif mode == "explore":
            return self._discover_hidden_gems()
        
        elif mode == "based_on_library":
            return self._discover_based_on_library(params.get("librarian"), params.get("top_artists", []))
        
        else:
            self.log("warning", f"Unknown discovery mode: {mode}")
            return []
    
    def _discover_similar_artists(self, artist: str, top_k: int = 5) -> List[CandidateSong]:
        """发现相似艺术家的热门歌曲"""
        candidates = []
        if not artist:
            return candidates
        
        try:
            # 搜索艺术家获取ID
            search_url = "https://music.163.com/api/search/get"
            params = {"s": artist, "type": 100, "offset": 0, "limit": 1}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(search_url, params=params, headers=headers, timeout=10)
            data = resp.json()
            
            if data.get("result") and data["result"].get("artists"):
                artist_id = data["result"]["artists"][0]["id"]
                artist_name = data["result"]["artists"][0]["name"]
                
                # 获取该艺术家的热门歌曲作为"参考风格"
                songs_url = f"https://music.163.com/api/artist/top/song?id={artist_id}"
                resp = requests.get(songs_url, headers=headers, timeout=10)
                data = resp.json()
                
                if data.get("songs"):
                    for song in data["songs"][:top_k]:
                        candidates.append(CandidateSong(
                            title=song.get("name", ""),
                            artist=", ".join([a.get("name", "") for a in song.get("artists", [])]),
                            source="netease_similar",
                            source_url=f"https://music.163.com/song?id={song.get('id')}",
                            discovered_at=datetime.now(),
                            genre_tags=[],
                            metadata={
                                "album": song.get("album", {}).get("name", ""),
                                "reason": f"与 {artist_name} 风格相似的热门歌曲",
                                "similar_to": artist_name
                            }
                        ))
        
        except Exception as e:
            self.log("error", f"Similar artist discovery failed: {e}")
        
        return candidates
    
    def _discover_by_mood(self, mood: str) -> List[CandidateSong]:
        """
        根据心情/场景发现音乐
        mood: work|study|workout|relax|sleep|party|commute
        """
        candidates = []
        
        # 心情 -> 歌单映射（网易云官方歌单ID）
        mood_playlists = {
            "work": {"id": 2829883282, "name": "专注工作"},
            "study": {"id": 21828943, "name": "学习专注"},
            "workout": {"id": 2821115454, "name": "运动健身"},
            "relax": {"id": 2829816518, "name": "轻松放松"},
            "sleep": {"id": 2807807602, "name": "睡眠助眠"},
            "party": {"id": 2829884372, "name": "派对嗨歌"},
            "commute": {"id": 2829884818, "name": "通勤路上"},
        }
        
        playlist_info = mood_playlists.get(mood)
        if not playlist_info:
            self.log("warning", f"Unknown mood: {mood}, using relax")
            playlist_info = mood_playlists["relax"]
        
        try:
            url = f"https://music.163.com/api/playlist/detail?id={playlist_info['id']}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            
            if data.get("result") and data["result"].get("tracks"):
                for track in data["result"]["tracks"][:10]:
                    candidates.append(CandidateSong(
                        title=track.get("name", ""),
                        artist=", ".join([a.get("name", "") for a in track.get("artists", [])]),
                        source="netease_mood",
                        source_url=f"https://music.163.com/song?id={track.get('id')}",
                        discovered_at=datetime.now(),
                        genre_tags=[mood],
                        metadata={
                            "album": track.get("album", {}).get("name", ""),
                            "reason": f"适合{mood}场景 - {playlist_info['name']}",
                            "mood": mood
                        }
                    ))
        
        except Exception as e:
            self.log("error", f"Mood discovery failed: {e}")
        
        return candidates
    
    def _discover_artist_new(self, artist: str) -> List[CandidateSong]:
        """发现特定艺术家的最新歌曲"""
        candidates = []
        if not artist:
            return candidates
        
        try:
            # 搜索艺术家
            search_url = "https://music.163.com/api/search/get"
            params = {"s": artist, "type": 100, "offset": 0, "limit": 1}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(search_url, params=params, headers=headers, timeout=10)
            data = resp.json()
            
            if data.get("result") and data["result"].get("artists"):
                artist_id = data["result"]["artists"][0]["id"]
                artist_name = data["result"]["artists"][0]["name"]
                
                # 获取最新专辑
                albums_url = f"https://music.163.com/api/artist/albums/{artist_id}?limit=3"
                resp = requests.get(albums_url, headers=headers, timeout=10)
                data = resp.json()
                
                if data.get("hotAlbums"):
                    for album in data["hotAlbums"][:2]:  # 最近2张专辑
                        album_id = album.get("id")
                        album_name = album.get("name")
                        publish_time = album.get("publishTime", 0)
                        
                        # 获取专辑歌曲
                        album_url = f"https://music.163.com/api/album/{album_id}"
                        resp = requests.get(album_url, headers=headers, timeout=10)
                        album_data = resp.json()
                        
                        album_detail = album_data.get("album") or album_data.get("data", {}).get("album")
                        if album_detail and album_detail.get("songs"):
                            for song in album_detail["songs"][:3]:  # 每张专辑取3首
                                candidates.append(CandidateSong(
                                    title=song.get("name", ""),
                                    artist=artist_name,
                                    source="netease_new_release",
                                    source_url=f"https://music.163.com/song?id={song.get('id')}",
                                    discovered_at=datetime.now(),
                                    genre_tags=[],
                                    metadata={
                                        "album": album_name,
                                        "reason": f"{artist_name} 最新专辑《{album_name}》",
                                        "publish_time": publish_time
                                    }
                                ))
        
        except Exception as e:
            self.log("error", f"Artist new release discovery failed: {e}")
        
        return candidates
    
    def _discover_hidden_gems(self) -> List[CandidateSong]:
        """发现小众/冷门但高质量的音乐"""
        candidates = []
        
        try:
            # 使用网易云的独立音乐榜或小众歌单
            # 这里用一个独立音乐歌单作为示例
            playlist_id = 101690677  # 独立音乐精选
            
            url = f"https://music.163.com/api/playlist/detail?id={playlist_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            
            if data.get("result") and data["result"].get("tracks"):
                # 筛选播放次数相对较低但评论质量高的
                tracks = data["result"]["tracks"]
                # 简单策略：取中间段（不是最热门也不是最冷门）
                mid_start = len(tracks) // 3
                for track in tracks[mid_start:mid_start+10]:
                    #  popularity < 80 认为是小众
                    if track.get("popularity", 100) < 80:
                        candidates.append(CandidateSong(
                            title=track.get("name", ""),
                            artist=", ".join([a.get("name", "") for a in track.get("artists", [])]),
                            source="netease_hidden",
                            source_url=f"https://music.163.com/song?id={track.get('id')}",
                            discovered_at=datetime.now(),
                            genre_tags=["小众", "独立"],
                            metadata={
                                "album": track.get("album", {}).get("name", ""),
                                "reason": "小众独立音乐，值得探索",
                                "popularity": track.get("popularity", 0)
                            }
                        ))
        
        except Exception as e:
            self.log("error", f"Hidden gems discovery failed: {e}")
        
        return candidates

    
    def _discover_based_on_library(self, librarian, top_artists: List[str]) -> List[CandidateSong]:
        """
        基于用户音乐库推荐相似歌曲
        
        策略：
        1. 取用户库中最常听的艺术家（Top 3）
        2. 为每个艺术家发现其热门歌曲（作为"风格参考"）
        3. 合并去重，优先推荐与用户库风格接近的
        """
        candidates = []
        
        if not top_artists:
            self.log("warning", "No top artists provided for library-based discovery")
            return candidates
        
        self.log("info", f"Discovering based on library artists: {top_artists[:3]}")
        
        # 为每个 top 艺术家获取相似歌曲
        for artist in top_artists[:3]:  # 最多取前3个艺术家
            try:
                # 搜索艺术家获取ID
                search_url = "https://music.163.com/api/search/get"
                params = {"s": artist, "type": 100, "offset": 0, "limit": 1}
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://music.163.com/"
                }
                
                resp = requests.get(search_url, params=params, headers=headers, timeout=10)
                data = resp.json()
                
                if data.get("result") and data["result"].get("artists"):
                    artist_id = data["result"]["artists"][0]["id"]
                    artist_name = data["result"]["artists"][0]["name"]
                    
                    # 获取该艺术家的热门歌曲
                    songs_url = f"https://music.163.com/api/artist/top/song?id={artist_id}"
                    resp = requests.get(songs_url, headers=headers, timeout=10)
                    data = resp.json()
                    
                    if data.get("songs"):
                        # 取前3首作为代表
                        for song in data["songs"][:3]:
                            # 检查是否已经在用户库中（简单匹配）
                            song_title = song.get("name", "")
                            
                            candidates.append(CandidateSong(
                                title=song_title,
                                artist=", ".join([a.get("name", "") for a in song.get("artists", [])]),
                                source="netease_library_based",
                                source_url=f"https://music.163.com/song?id={song.get('id')}",
                                discovered_at=datetime.now(),
                                genre_tags=[],
                                metadata={
                                    "album": song.get("album", {}).get("name", ""),
                                    "reason": f"因为你喜欢听 {artist_name}（你库中Top艺术家）",
                                    "based_on_artist": artist_name,
                                    "similarity_type": "same_artist"  # 同艺术家推荐
                                }
                            ))
                        
                        # 同时尝试获取相似歌手（网易云没有直接的相似歌手API，这里用搜索关键词方式）
                        # 搜索 "artist_name 相似" 来找到风格相近的
                        sim_search = f"{artist_name}"
                        sim_params = {"s": sim_search, "type": 1, "offset": 0, "limit": 5}  # type=1 搜索歌曲
                        
                        resp = requests.get(search_url, params=sim_params, headers=headers, timeout=10)
                        sim_data = resp.json()
                        
                        if sim_data.get("result") and sim_data["result"].get("songs"):
                            for song in sim_data["result"]["songs"][:2]:  # 额外2首相似风格
                                other_artist = ", ".join([a.get("name", "") for a in song.get("artists", [])])
                                
                                # 避免重复添加同艺术家的歌
                                if artist_name not in other_artist:
                                    candidates.append(CandidateSong(
                                        title=song.get("name", ""),
                                        artist=other_artist,
                                        source="netease_library_based",
                                        source_url=f"https://music.163.com/song?id={song.get('id')}",
                                        discovered_at=datetime.now(),
                                        genre_tags=[],
                                        metadata={
                                            "album": song.get("album", {}).get("name", ""),
                                            "reason": f"风格与你喜欢的 {artist_name} 相近",
                                            "based_on_artist": artist_name,
                                            "similarity_type": "similar_style"  # 风格相似
                                        }
                                    ))
            
            except Exception as e:
                self.log("error", f"Library-based discovery failed for {artist}: {e}")
                continue
        
        # 去重（基于歌曲ID）
        seen_ids = set()
        unique_candidates = []
        for c in candidates:
            song_id = f"{c.artist}-{c.title}"
            if song_id not in seen_ids:
                seen_ids.add(song_id)
                unique_candidates.append(c)
        
        self.log("info", f"Library-based discovery: {len(unique_candidates)} unique songs from {len(top_artists)} artists")
        return unique_candidates[:15]  # 最多返回15首
