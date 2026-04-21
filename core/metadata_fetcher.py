"""
Metadata Fetcher - 元数据获取
"""
from typing import Dict, Optional, Any
from pathlib import Path
import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON
import requests
import time


class MetadataFetcher:
    """
    元数据获取器
    - 从本地文件提取元数据
    - 从MusicBrainz查询补充
    - 指纹匹配查询
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.musicbrainz_base = "https://musicbrainz.org/ws/2"
        self.user_agent = config.get("musicbrainz_user_agent", "MusicAgent/1.0")
        self._last_request_time = 0
        self._min_interval = 1.0  # MusicBrainz速率限制
        
    def extract_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        从音频文件提取元数据
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        
        try:
            if ext == ".flac":
                return self._parse_flac(file_path)
            elif ext == ".mp3":
                return self._parse_mp3(file_path)
            else:
                return self._parse_generic(file_path)
        except Exception as e:
            print(f"Failed to parse {file_path}: {e}")
            return self._fallback_parse(file_path)
    
    def query_by_fingerprint(self, fingerprint: str) -> Optional[Dict]:
        """
        通过音频指纹查询元数据
        """
        # 这里需要集成AcoustID API
        # 简化版本：返回空
        return None
    
    def query_by_name(self, artist: str, title: str) -> Dict:
        """
        通过艺术家和标题查询MusicBrainz
        
        Args:
            artist: 艺术家名
            title: 歌曲标题
            
        Returns:
            元数据字典
        """
        self._rate_limit()
        
        try:
            params = {
                "query": f'artist:"{artist}" AND recording:"{title}"',
                "fmt": "json",
                "limit": 1
            }
            
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "application/json"
            }
            
            response = requests.get(
                f"{self.musicbrainz_base}/recording/",
                params=params,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("recordings"):
                recording = data["recordings"][0]
                
                # 解析结果
                result = {
                    "title": recording.get("title"),
                    "artist": recording.get("artist-credit", [{}])[0].get("name", artist),
                    "duration": recording.get("length", 0) / 1000,  # ms to s
                    "genres": []
                }
                
                # 获取流派标签
                if recording.get("tags"):
                    result["genres"] = [t["name"] for t in recording["tags"][:5]]
                
                # 获取发行信息
                if recording.get("releases"):
                    release = recording["releases"][0]
                    result["album"] = release.get("title")
                    if release.get("date"):
                        result["year"] = int(release["date"][:4]) if release["date"][:4].isdigit() else 0
                
                return result
            
            return {"artist": artist, "title": title}
            
        except Exception as e:
            print(f"MusicBrainz query failed: {e}")
            return {"artist": artist, "title": title}
    
    def _parse_flac(self, file_path: str) -> Dict:
        """解析FLAC文件"""
        audio = FLAC(file_path)
        
        return {
            "title": audio.get("TITLE", [Path(file_path).stem])[0],
            "artist": audio.get("ARTIST", ["Unknown"])[0],
            "album": audio.get("ALBUM", ["Unknown"])[0],
            "genre": audio.get("GENRE", [""])[0],
            "year": int(audio.get("DATE", ["0"])[0][:4]) if audio.get("DATE") else 0,
            "duration": audio.info.length if audio.info else 0,
            "tags": list(audio.keys())
        }
    
    def _parse_mp3(self, file_path: str) -> Dict:
        """解析MP3文件"""
        audio = MP3(file_path)
        
        result = {
            "duration": audio.info.length if audio.info else 0,
            "title": Path(file_path).stem,
            "artist": "Unknown",
            "album": "Unknown",
            "genre": "",
            "year": 0,
            "tags": []
        }
        
        if audio.tags:
            result["title"] = str(audio.tags.get("TIT2", result["title"]))
            result["artist"] = str(audio.tags.get("TPE1", "Unknown"))
            result["album"] = str(audio.tags.get("TALB", "Unknown"))
            result["genre"] = str(audio.tags.get("TCON", ""))
            date = str(audio.tags.get("TDRC", "0"))
            if date[:4].isdigit():
                result["year"] = int(date[:4])
        
        return result
    
    def _parse_generic(self, file_path: str) -> Dict:
        """通用解析"""
        audio = mutagen.File(file_path)
        
        return {
            "duration": audio.info.length if audio and audio.info else 0,
            "title": Path(file_path).stem,
            "artist": "Unknown",
            "album": "Unknown",
            "genre": "",
            "year": 0,
            "tags": list(audio.keys()) if audio else []
        }
    
    def _fallback_parse(self, file_path: str) -> Dict:
        """文件名解析回退"""
        path = Path(file_path)
        
        # 尝试从文件名解析 "Artist - Title"
        name = path.stem
        if " - " in name:
            parts = name.split(" - ", 1)
            return {
                "title": parts[1].strip(),
                "artist": parts[0].strip(),
                "album": "Unknown",
                "genre": "",
                "year": 0,
                "duration": 0,
                "tags": []
            }
        
        return {
            "title": name,
            "artist": "Unknown",
            "album": "Unknown",
            "genre": "",
            "year": 0,
            "duration": 0,
            "tags": []
        }
    
    def _rate_limit(self):
        """MusicBrainz速率限制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
