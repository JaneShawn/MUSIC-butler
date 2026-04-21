"""
Lyrics Fetcher - 歌词获取器
支持本地文件和在线API
"""
import os
from pathlib import Path
from typing import Optional, Dict
import requests
import json
from datetime import datetime


class LyricsFetcher:
    """歌词获取器"""
    
    def __init__(self, lyrics_dir: str = "data/lyrics"):
        self.cache_dir = Path("data/lyrics_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 专门的歌词保存目录（不是缓存，是用户可见的歌词文件）
        self.lyrics_dir = Path(lyrics_dir)
        self.lyrics_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch(self, title: str, artist: str, file_path: str) -> Optional[str]:
        """
        获取歌词（多源尝试）
        
        优先级：
        1. 专用歌词目录（data/lyrics/）
        2. 本地 .lrc 文件（歌曲同目录）
        3. 缓存
        4. 网易云API
        """
        # 1. 检查专用歌词目录
        lyrics = self._from_lyrics_dir(title, artist)
        if lyrics:
            return lyrics
        
        # 2. 检查本地 lrc 文件
        lyrics = self._from_local_file(file_path)
        if lyrics:
            return lyrics
        
        # 3. 检查缓存
        cache_key = self._get_cache_key(title, artist)
        cache_file = self.cache_dir / f"{cache_key}.txt"
        if cache_file.exists():
            return cache_file.read_text(encoding='utf-8')
        
        # 4. 从网易云获取
        lyrics = self._from_netease(title, artist)
        if lyrics:
            # 保存缓存
            cache_file.write_text(lyrics, encoding='utf-8')
            return lyrics
        
        return None
    
    def _from_lyrics_dir(self, title: str, artist: str) -> Optional[str]:
        """检查专用歌词目录"""
        # 生成安全的文件名
        safe_name = self._safe_filename(f"{artist} - {title}")
        lrc_path = self.lyrics_dir / f"{safe_name}.lrc"
        
        if lrc_path.exists():
            return lrc_path.read_text(encoding='utf-8')
        
        # 也尝试只用歌名
        safe_title = self._safe_filename(title)
        lrc_path2 = self.lyrics_dir / f"{safe_title}.lrc"
        if lrc_path2.exists():
            return lrc_path2.read_text(encoding='utf-8')
        
        return None
    
    def _safe_filename(self, name: str) -> str:
        """生成安全的文件名"""
        # 移除非法字符
        illegal = '<>:"/\\|?*'
        for c in illegal:
            name = name.replace(c, '_')
        return name.strip()
    
    def save_to_lyrics_dir(self, title: str, artist: str, lyrics: str) -> bool:
        """保存歌词到专用目录（供批量下载使用）"""
        try:
            safe_name = self._safe_filename(f"{artist} - {title}")
            lrc_path = self.lyrics_dir / f"{safe_name}.lrc"
            lrc_path.write_text(lyrics, encoding='utf-8')
            return True
        except Exception as e:
            print(f"[WARN] 保存歌词失败: {e}")
            return False
    
    def _from_local_file(self, file_path: str) -> Optional[str]:
        """查找同目录下的 .lrc 文件"""
        base_path = Path(file_path).with_suffix('.lrc')
        
        # 尝试多个可能的歌词文件名
        possible_names = [
            base_path,  # song.lrc
            base_path.with_suffix('.LRC'),
            Path(file_path).parent / f"{Path(file_path).stem}.lrc",
        ]
        
        for lrc_path in possible_names:
            if lrc_path.exists():
                return lrc_path.read_text(encoding='utf-8')
        
        return None
    
    def _from_netease(self, title: str, artist: str) -> Optional[str]:
        """从网易云音乐API获取歌词"""
        try:
            # 先搜索歌曲
            search_url = "https://music.163.com/api/search/get"
            params = {
                "s": f"{title} {artist}",
                "type": 1,  # 搜索歌曲
                "offset": 0,
                "limit": 5
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(search_url, params=params, headers=headers, timeout=10)
            data = resp.json()
            
            if not data.get("result") or not data["result"].get("songs"):
                return None
            
            # 找最匹配的歌曲
            best_match = None
            for song in data["result"]["songs"]:
                song_title = song.get("name", "").lower()
                if title.lower() in song_title or song_title in title.lower():
                    best_match = song
                    break
            
            if not best_match:
                best_match = data["result"]["songs"][0]
            
            song_id = best_match.get("id")
            if not song_id:
                return None
            
            # 获取歌曲详情（包含语言信息）
            try:
                detail_url = f"https://music.163.com/api/song/detail?ids=[{song_id}]"
                resp = requests.get(detail_url, headers=headers, timeout=5)
                detail_data = resp.json()
                
                # 保存语言信息到缓存文件（必须映射为标准中文名）
                if detail_data.get("songs"):
                    song_detail = detail_data["songs"][0]
                    raw_lang = song_detail.get("language", "")
                    if raw_lang:
                        lang_map = {
                            'ZH': '国语', 'zh': '国语', '中文': '国语',
                            'HK': '粤语', 'hk': '粤语', '粤': '粤语',
                            'EN': '英语', 'en': '英语', '英文': '英语',
                            'JA': '日语', 'ja': '日语', 'JP': '日语', '日文': '日语',
                            'KO': '韩语', 'ko': '韩语', 'KR': '韩语', '韩文': '韩语',
                        }
                        mapped_lang = lang_map.get(raw_lang, raw_lang)
                        self._save_language_to_cache(title, artist, mapped_lang)
            except:
                pass  # 语言获取失败不影响歌词获取
            
            # 获取歌词
            lyric_url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"
            resp = requests.get(lyric_url, headers=headers, timeout=10)
            lyric_data = resp.json()
            
            # 优先获取翻译歌词，否则原版
            lrc = lyric_data.get("lrc", {})
            lyric_text = lrc.get("lyric", "")
            
            # 清理歌词（移除时间戳）
            lyric_text = self._clean_lrc(lyric_text)
            
            if len(lyric_text) > 50:  # 确保歌词有效
                return lyric_text
            
        except Exception as e:
            print(f"[WARN] NetEase lyrics fetch failed: {e}")
        
        return None
    
    def _clean_lrc(self, lrc_text: str) -> str:
        """清理LRC格式歌词（支持多种时间戳格式）"""
        import re
        # 移除时间戳 [00:12] / [00:12.3] / [00:12.34] / [00:12.345]
        text = re.sub(r'\[\d{2}:\d{2}(?:\.\d{1,3})?\]', '', lrc_text)
        # 移除元信息 [ar:艺术家] / [ti:标题] / [al:专辑]
        text = re.sub(r'\[(ar|ti|al|by|offset):[^\]]*\]', '', text, flags=re.IGNORECASE)
        # 移除空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return '\n'.join(lines)
    
    def _get_cache_key(self, title: str, artist: str) -> str:
        """生成缓存key"""
        import hashlib
        key = f"{title}-{artist}".encode('utf-8')
        return hashlib.md5(key).hexdigest()[:16]
    
    def _save_language_to_cache(self, title: str, artist: str, language: str):
        """保存语言信息到缓存（供LanguageManager使用）"""
        try:
            import json
            from pathlib import Path
            
            cache_file = Path("data/netease_language_cache.json")
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            cache = {}
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            
            cache_key = f"{artist}-{title}"
            cache[cache_key] = {
                "language": language,
                "source": "netease_api",
                "timestamp": str(datetime.now())
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"[WARN] 保存语言缓存失败: {e}")
    
    def get_language_from_netease(self, title: str, artist: str) -> Optional[str]:
        """
        从网易云API获取歌曲语言（不下载歌词）
        返回: 语言字符串 或 None
        """
        try:
            # 先检查缓存
            import json
            from pathlib import Path
            cache_file = Path("data/netease_language_cache.json")
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                cache_key = f"{artist}-{title}"
                if cache_key in cache:
                    return cache[cache_key]["language"]
            
            # 搜索歌曲
            search_url = "https://music.163.com/api/search/get"
            params = {"s": f"{title} {artist}", "type": 1, "offset": 0, "limit": 3}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(search_url, params=params, headers=headers, timeout=10)
            data = resp.json()
            
            if not data.get("result") or not data["result"].get("songs"):
                return None
            
            best_match = data["result"]["songs"][0]
            song_id = best_match.get("id")
            
            # 获取详情
            detail_url = f"https://music.163.com/api/song/detail?ids=[{song_id}]"
            resp = requests.get(detail_url, headers=headers, timeout=10)
            detail_data = resp.json()
            
            if detail_data.get("songs"):
                language = detail_data["songs"][0].get("language", "")
                if language:
                    # 转换为标准格式
                    lang_map = {
                        'ZH': '国语', 'zh': '国语', '中文': '国语',
                        'HK': '粤语', 'hk': '粤语', '粤': '粤语',
                        'EN': '英语', 'en': '英语', '英文': '英语',
                        'JA': '日语', 'ja': '日语', 'JP': '日语', '日文': '日语',
                        'KO': '韩语', 'ko': '韩语', 'KR': '韩语', '韩文': '韩语',
                    }
                    result = lang_map.get(language, language)
                    self._save_language_to_cache(title, artist, result)
                    return result
                    
        except Exception as e:
            print(f"[WARN] 获取语言失败: {e}")
        
        return None
    
    def batch_fetch(self, songs: list, progress_callback=None) -> Dict[str, str]:
        """批量获取歌词"""
        results = {}
        for i, song in enumerate(songs):
            lyrics = self.fetch(
                song.get('title', ''),
                song.get('artist', ''),
                song.get('file_path', '')
            )
            if lyrics:
                results[song.get('file_path')] = lyrics
            
            if progress_callback:
                progress_callback(i + 1, len(songs))
        
        return results
