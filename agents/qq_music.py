"""
QQ Music API - 获取专辑信息和封面

使用 QQ 音乐公开 API 搜索歌曲、专辑信息
"""
import re
import json
import hashlib
import time
from typing import Dict, Optional, List, Tuple
from pathlib import Path
import requests


class QQMusicAPI:
    """QQ 音乐 API 封装"""
    
    def __init__(self):
        self.base_url = "https://u.y.qq.com/cgi-bin/musicu.fcg"
        self.search_url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://y.qq.com/",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.cache: Dict[str, Dict] = {}
    
    def search_song(self, title: str, artist: str = None) -> Optional[Dict]:
        """
        搜索歌曲，返回最佳匹配结果（包含专辑信息）
        
        Returns:
            {
                "title": "歌曲名",
                "artist": "歌手",
                "album": "专辑名",
                "album_id": "专辑ID",
                "cover_url": "封面URL",
                "year": 2023,
                "genre": "流派"
            }
        """
        cache_key = f"{artist or ''}_{title}".lower()
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            # 构建搜索关键词
            if artist:
                keyword = f"{artist} {title}"
            else:
                keyword = title
            
            params = {
                "ct": 24,
                "qqmusic_ver": 1298,
                "new_json": 1,
                "remoteplace": "txt.yqq.song",
                "searchid": "",
                "t": 0,
                "aggr": 1,
                "cr": 1,
                "catZhida": 1,
                "lossless": 0,
                "flag_qc": 0,
                "p": 1,
                "n": 10,
                "w": keyword,
                "g_tk": 5381,
                "format": "json",
            }
            
            response = requests.get(
                self.search_url,
                params=params,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            
            if data.get("code") != 0:
                return None
            
            songs = data.get("data", {}).get("song", {}).get("list", [])
            if not songs:
                return None
            
            # 找到最佳匹配
            best_match = self._find_best_match(songs, title, artist)
            if not best_match:
                return None
            
            # 提取信息
            result = self._extract_song_info(best_match)
            self.cache[cache_key] = result
            return result
            
        except Exception as e:
            print(f"  QQ音乐搜索失败: {e}")
            return None
    
    def _find_best_match(self, songs: List[Dict], title: str, artist: str = None) -> Optional[Dict]:
        """找到最佳匹配的歌曲"""
        title_lower = title.lower()
        artist_lower = (artist or "").lower()
        
        best_score = 0
        best_match = None
        
        for song in songs:
            song_title = song.get("songname", "")
            song_artist = song.get("singer", [{}])[0].get("name", "") if song.get("singer") else ""
            
            # 计算匹配分数
            score = 0
            
            # 标题匹配
            if title_lower in song_title.lower() or song_title.lower() in title_lower:
                score += 50
            
            # 艺术家匹配
            if artist_lower and song_artist:
                if artist_lower in song_artist.lower() or song_artist.lower() in artist_lower:
                    score += 50
            
            # 完全匹配加分
            if song_title.lower() == title_lower:
                score += 20
            
            if score > best_score:
                best_score = score
                best_match = song
        
        # 阈值：至少需要标题匹配
        return best_match if best_score >= 50 else None
    
    def _extract_song_info(self, song: Dict) -> Dict:
        """从歌曲数据中提取信息"""
        # 歌手信息
        singers = song.get("singer", [])
        artist_name = singers[0].get("name", "") if singers else ""
        
        # 专辑信息
        album_info = song.get("album", {})
        album_name = album_info.get("name", "")
        album_id = album_info.get("mid", "") or album_info.get("id", "")
        
        # 封面 URL（使用专辑封面）
        # QQ 音乐封面格式：https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_mid}.jpg
        cover_url = ""
        if album_id:
            cover_url = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_id}.jpg"
        elif album_info.get("pmid"):
            cover_url = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_info.get('pmid')}.jpg"
        
        # 年份（从专辑时间）
        year = 0
        time_public = song.get("time_public", "") or album_info.get("time_public", "")
        if time_public and len(time_public) >= 4:
            try:
                year = int(time_public[:4])
            except (ValueError, IndexError):
                pass
        
        return {
            "title": song.get("songname", ""),
            "artist": artist_name,
            "album": album_name,
            "album_id": album_id,
            "cover_url": cover_url,
            "year": year,
            "genre": "",  # QQ 音乐 API 不直接返回流派
            "source": "qq_music"
        }
    
    def download_cover(self, cover_url: str, save_path: Path) -> bool:
        """下载封面图片"""
        if not cover_url:
            return False
        
        try:
            response = requests.get(cover_url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(response.content)
                return True
        except Exception as e:
            print(f"  封面下载失败: {e}")
        
        return False


def test_qq_music():
    """测试 QQ 音乐 API"""
    api = QQMusicAPI()
    
    # 测试搜索
    result = api.search_song("晴天", "周杰伦")
    if result:
        print(f"搜索结果: {result}")
        print(f"封面URL: {result.get('cover_url')}")
    else:
        print("未找到")


if __name__ == "__main__":
    test_qq_music()
