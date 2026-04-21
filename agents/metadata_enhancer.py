"""
Metadata Enhancer - 在线搜索元数据并重命名文件

功能：
- 使用 MusicBrainz API 搜索歌曲信息
- 使用 LLM 智能解析文件名
- 网易云音乐搜索（中文歌曲）
- QQ音乐搜索（专辑+封面）
- 本地智能解析 "Artist - Title" 格式
- 用 AcoustID 音频指纹精准识别
"""
import os
import re
import time
import json
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from difflib import SequenceMatcher

import requests

from .qq_music import QQMusicAPI


class MetadataEnhancer:
    """
    元数据增强器（多源搜索）
    """
    
    def __init__(self, cache: Optional[Dict] = None, kimi_client=None, enable_qq: bool = True):
        self.base_url = "https://musicbrainz.org/ws/2"
        self.user_agent = "MusicAgent/1.0 (your-email@example.com)"
        self.last_request_time = 0
        self.min_interval = 1.0
        self.cache = cache or {}
        self.timeout = 5
        self.max_retries = 2
        self.kimi = kimi_client  # LLM 客户端
        
        # 初始化 QQ 音乐 API
        self.qq_music = QQMusicAPI() if enable_qq else None
        self.covers_dir = Path("./data/covers")
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        
    def search_by_filename(self, filename: str, use_llm: bool = True, use_163: bool = True, 
                           use_qq: bool = True, download_cover: bool = False) -> Optional[Dict]:
        """
        多源搜索元数据（智能选择最佳策略）
        
        搜索优先级（在线优先）：
        1. QQ音乐（带专辑+封面，中文优先）
        2. 网易云音乐（中文歌曲）
        3. MusicBrainz（英文歌曲）
        4. LLM智能解析
        5. 本地解析（兜底）
        """
        cache_key = filename.lower()
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # 步骤0: 先本地解析获取搜索关键词（不直接返回结果）
        local_result = self._parse_local(filename)
        if local_result and local_result.get('confidence', 0) > 0.8:
            search_artist = local_result.get('artist')
            search_title = local_result.get('title')
        else:
            clean_name = self._clean_filename(filename)
            if " - " in clean_name:
                parts = clean_name.split(" - ", 1)
                search_artist = parts[0].strip()
                search_title = parts[1].strip()
            else:
                search_artist = None
                search_title = clean_name
        
        result = None
        
        # 策略1: QQ音乐搜索（优先，中文歌曲效果好，带专辑+封面）
        if use_qq and self.qq_music and search_title:
            print(f"  [搜索QQ音乐] {search_artist or ''} - {search_title}")
            try:
                result = self.qq_music.search_song(search_title, search_artist)
                if result:
                    print(f"  [QQ音乐找到] {result.get('artist')} - {result.get('title')}")
                    cover_url = result.get('cover_url')
                    if cover_url:
                        print(f"  [封面URL] {cover_url[:50]}...")
                        if download_cover:
                            print(f"  [下载封面] ...")
                            cover_path = self._download_cover(cover_url, result['album_id'] or result['title'])
                            if cover_path:
                                result['cover_path'] = str(cover_path)
                                print(f"  [封面下载成功]")
                            else:
                                print(f"  [封面下载失败]")
                    else:
                        print(f"  [封面URL] 无，尝试网易云获取封面...")
                        # QQ找到歌但无封面，尝试用网易云获取封面
                        netease_result = self._search_netease(filename, search_artist, search_title)
                        if netease_result and netease_result.get('cover_url'):
                            result['cover_url'] = netease_result['cover_url']
                            if download_cover:
                                cover_path = self._download_cover(netease_result['cover_url'], result['album_id'] or result['title'])
                                if cover_path:
                                    result['cover_path'] = str(cover_path)
                    self.cache[cache_key] = result
                    return result
                else:
                    print(f"  [QQ音乐未找到，尝试网易云...]")
            except Exception as e:
                print(f"  [QQ音乐搜索出错] {e}")
        
        # 策略2: 网易云音乐搜索（中文歌曲）
        if use_163 and search_title:
            print(f"  [搜索网易云] {search_artist or ''} - {search_title}")
            result = self._search_netease(filename, search_artist, search_title)
            if result:
                print(f"  [网易云找到] {result.get('artist')} - {result.get('title')}")
                print(f"     封面URL: {result.get('cover_url', '无')[:60]}..." if result.get('cover_url') else "     封面URL: 无")
                if download_cover and result.get('cover_url'):
                    print(f"  [下载封面] ...")
                    cover_path = self._download_cover(result['cover_url'], result.get('album', result['title']))
                    if cover_path:
                        result['cover_path'] = str(cover_path)
                        print(f"  [封面下载成功]")
                    else:
                        print(f"  [封面下载失败]")
                self.cache[cache_key] = result
                return result
            else:
                print(f"  [网易云未找到]")
        
        # 策略3: MusicBrainz（英文歌曲）
        print(f"  [搜索MusicBrainz] {search_title}")
        result = self._search_musicbrainz(filename)
        if result:
            print(f"  [MusicBrainz找到] {result.get('artist')} - {result.get('title')}")
            self.cache[cache_key] = result
            return result
        else:
            print(f"  [MusicBrainz未找到]")
        
        # 策略4: LLM智能解析（适合复杂/中文文件名）
        if use_llm and self.kimi:
            print(f"  🤖 使用LLM解析文件名")
            result = self._parse_with_llm(filename)
            if result:
                print(f"  [LLM解析成功]")
                self.cache[cache_key] = result
                return result
        
        # 策略5: 本地解析兜底（如果之前有解析结果）
        if local_result and local_result.get('confidence', 0) > 0.5:
            print(f"  [本地解析结果]")
            self.cache[cache_key] = local_result
            return local_result
        
        # 缓存空结果
        print(f"  [所有数据源均未找到]")
        self.cache[cache_key] = None
        return None
    
    def _download_cover(self, cover_url: str, identifier: str) -> Optional[Path]:
        """下载封面图片到本地（带重试和回退）"""
        if not cover_url or not identifier:
            return None
        
        # 确保目录存在
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成安全的文件名
        safe_id = re.sub(r'[^\w\-]', '_', identifier)[:50]
        cover_path = self.covers_dir / f"{safe_id}.jpg"
        
        if cover_path.exists():
            return cover_path
        
        # 尝试下载（最多2次）
        for attempt in range(2):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://y.qq.com/" if "qqimg.cn" in cover_url else ""
                }
                response = requests.get(cover_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    with open(cover_path, "wb") as f:
                        f.write(response.content)
                    return cover_path
                elif response.status_code in (403, 404) and attempt == 0:
                    # 尝试替换为更小的尺寸或备用域名
                    if "y.gtimg.cn" in cover_url:
                        alt_url = cover_url.replace("T002R300x300M000", "T002R150x150M000")
                        cover_url = alt_url
                        continue
            except Exception:
                if attempt == 0:
                    continue
        
        return None
    
    def _parse_local(self, filename: str) -> Optional[Dict]:
        """
        本地智能解析文件名
        支持格式：
        - "Artist - Title"
        - "Artist – Title"（中文破折号）
        - "Artist-Title"
        - "01. Artist - Title"
        - 纯中文 "歌手 - 歌名"
        """
        name = Path(filename).stem
        
        # 移除编号前缀 (01. 01- 等)
        name = re.sub(r'^\d+[\.\-\s]+', '', name)
        
        # 标准化分隔符
        name = name.replace(' – ', ' - ').replace('—', ' - ')
        
        # 尝试 "Artist - Title" 格式
        if ' - ' in name:
            parts = name.split(' - ', 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            
            # 清理 artist 和 title
            artist = self._clean_text(artist)
            title = self._clean_text(title)
            
            if artist and title and len(artist) < 100 and len(title) < 100:
                return {
                    "title": title,
                    "artist": artist,
                    "album": "",
                    "year": 0,
                    "genre": "",
                    "confidence": 0.9,
                    "source": "local_parse"
                }
        
        # 尝试 "Artist-Title" 格式
        if '-' in name and ' - ' not in name:
            parts = name.split('-', 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            
            artist = self._clean_text(artist)
            title = self._clean_text(title)
            
            if artist and title and len(artist) < 100 and len(title) < 100:
                return {
                    "title": title,
                    "artist": artist,
                    "album": "",
                    "year": 0,
                    "genre": "",
                    "confidence": 0.8,
                    "source": "local_parse"
                }
        
        return None
    
    def _parse_with_llm(self, filename: str) -> Optional[Dict]:
        """
        使用 LLM 智能解析文件名
        """
        if not self.kimi:
            return None
        
        try:
            system_prompt = """你是一个音乐文件名解析专家。从文件名中提取歌手和歌名。

规则：
1. 文件名通常是 "歌手 - 歌名" 或 "歌手-歌名" 格式
2. 可能包含编号、扩展名等噪音
3. 可能是中文、英文或混合

只返回 JSON 格式：
{"artist": "歌手名", "title": "歌名"}

如果无法解析，返回：
{"artist": null, "title": null}"""

            prompt = f"文件名: {filename}\n提取歌手和歌名："
            
            response = self.kimi.generate(
                prompt, 
                system=system_prompt,
                temperature=0.1,
                max_tokens=100
            )
            
            if response:
                # 提取 JSON
                json_match = re.search(r'\{[\s\S]*?\}', response)
                if json_match:
                    data = json.loads(json_match.group())
                    artist = data.get('artist')
                    title = data.get('title')
                    
                    if artist and title and artist != 'null' and title != 'null':
                        return {
                            "title": title,
                            "artist": artist,
                            "album": "",
                            "year": 0,
                            "genre": "",
                            "confidence": 0.85,
                            "source": "llm_parse"
                        }
        except Exception as e:
            print(f"  LLM解析失败: {e}")
        
        return None
    
    def _get_netease_album_cover(self, album_id: int) -> Optional[str]:
        """获取网易云专辑封面URL"""
        if not album_id:
            return None
        try:
            # 尝试多个API端点
            endpoints = [
                f"https://music.163.com/api/album/{album_id}",
                f"https://music.163.com/api/v1/album/{album_id}",
            ]
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://music.163.com/",
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            
            for url in endpoints:
                try:
                    response = requests.get(url, headers=headers, timeout=self.timeout)
                    if response.status_code == 200:
                        data = response.json()
                        # 检查不同的响应格式
                        album_data = None
                        if data.get('album'):
                            album_data = data['album']
                        elif data.get('data', {}).get('album'):
                            album_data = data['data']['album']
                        
                        if album_data:
                            pic_url = album_data.get('picUrl')
                            if pic_url:
                                return pic_url
                except:
                    continue
                    
        except Exception as e:
            print(f"  [获取封面URL失败] {e}")
        return None
    
    def _search_netease(self, filename: str, artist_hint: str = None, title_hint: str = None) -> Optional[Dict]:
        """
        搜索网易云音乐（适合中文歌曲）
        使用公开 API，无需认证
        """
        try:
            # 确定搜索关键词
            if artist_hint and title_hint:
                keyword = f"{artist_hint} {title_hint}"
            else:
                keyword = Path(filename).stem
                # 移除扩展名和常见后缀
                keyword = self._clean_filename(keyword)
            
            # 网易云搜索 API
            url = "https://music.163.com/api/search/get"
            params = {
                "s": keyword,
                "type": 1,  # 单曲
                "limit": 5,
                "offset": 0
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('result') and data['result'].get('songs'):
                    songs = data['result']['songs']
                    
                    # 找最佳匹配
                    best_match = None
                    best_score = 0
                    
                    for song in songs:
                        song_title = song.get('name', '')
                        song_artists = ', '.join([a.get('name', '') for a in song.get('artists', [])])
                        album_data = song.get('album', {})
                        album = album_data.get('name', '')
                        album_id = album_data.get('id')
                        
                        # 获取专辑封面URL
                        cover_url = None
                        if album_data.get('picUrl'):
                            cover_url = album_data['picUrl']
                        
                        # 如果没有 picUrl 但有 album_id，从专辑API获取
                        if not cover_url and album_id:
                            print(f"  [从专辑API获取封面] album_id={album_id}")
                            cover_url = self._get_netease_album_cover(album_id)
                        
                        # 计算匹配分数
                        score = self._calculate_match_score(
                            filename, song_artists, song_title, artist_hint, title_hint
                        )
                        
                        if score > best_score:
                            best_score = score
                            best_match = {
                                "title": song_title,
                                "artist": song_artists,
                                "album": album,
                                "year": 0,
                                "genre": "",
                                "confidence": score,
                                "source": "netease",
                                "cover_url": cover_url
                            }
                    
                    # 如果匹配度足够高，返回结果
                    if best_match and best_score > 0.5:
                        # 确保封面URL已获取（如果之前失败了，再试一次）
                        if not best_match.get('cover_url') and best_match.get('album'):
                            # 重新搜索获取album_id
                            for song in songs:
                                if song.get('name') == best_match['title']:
                                    album_data = song.get('album', {})
                                    album_id = album_data.get('id')
                                    if album_id:
                                        print(f"  [再次尝试获取封面] album_id={album_id}")
                                        cover_url = self._get_netease_album_cover(album_id)
                                        if cover_url:
                                            best_match['cover_url'] = cover_url
                                            print(f"  [封面URL已获取]")
                                        break
                        return best_match
            
        except Exception as e:
            print(f"  [网易云搜索出错] {e}")
        
        return None
    
    def _search_musicbrainz(self, filename: str) -> Optional[Dict]:
        """
        搜索 MusicBrainz（适合英文歌曲）
        """
        clean_name = self._clean_filename(Path(filename).stem)
        
        # 尝试 "Artist - Title" 格式
        if " - " in clean_name:
            parts = clean_name.split(" - ", 1)
            artist_hint = parts[0].strip()
            title_hint = parts[1].strip()
            
            result = self._search_mb_recording(title_hint, artist=artist_hint)
            if result:
                return result
        
        # 整体搜索
        result = self._search_mb_recording(clean_name)
        if result:
            return result
        
        return None
    
    def _search_mb_recording(self, title: str, artist: str = None) -> Optional[Dict]:
        """搜索 MusicBrainz"""
        self._rate_limit()
        
        for attempt in range(self.max_retries):
            try:
                if artist:
                    query = f'recording:"{title}" AND artist:"{artist}"'
                else:
                    query = f'recording:"{title}"'
                
                params = {"query": query, "fmt": "json", "limit": 3}
                headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
                
                response = requests.get(
                    f"{self.base_url}/recording/",
                    params=params, headers=headers, timeout=self.timeout
                )
                response.raise_for_status()
                
                data = response.json()
                
                if data.get("recordings") and len(data["recordings"]) > 0:
                    recording = data["recordings"][0]
                    
                    artists = recording.get("artist-credit", [])
                    artist_name = artists[0].get("name", "Unknown") if artists else "Unknown"
                    
                    releases = recording.get("releases", [])
                    album = releases[0].get("title", "") if releases else ""
                    
                    year = 0
                    if releases and releases[0].get("date"):
                        date = releases[0]["date"]
                        if date[:4].isdigit():
                            year = int(date[:4])
                    
                    return {
                        "title": recording.get("title", ""),
                        "artist": artist_name,
                        "album": album,
                        "year": year,
                        "genre": "",
                        "source": "musicbrainz"
                    }
                
                return None
                
            except requests.Timeout:
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)
                    continue
                return None
            except Exception:
                return None
    
    def _calculate_match_score(self, filename: str, artist: str, title: str, 
                               artist_hint: str = None, title_hint: str = None) -> float:
        """计算匹配分数"""
        score = 0.0
        filename_lower = filename.lower()
        
        # 如果提供了提示，优先比较
        if artist_hint and title_hint:
            artist_sim = self.calculate_similarity(artist_hint, artist)
            title_sim = self.calculate_similarity(title_hint, title)
            score = artist_sim * 0.4 + title_sim * 0.6
        else:
            # 否则看是否在文件名中出现
            artist_in_file = artist.lower() in filename_lower
            title_in_file = title.lower() in filename_lower
            
            if artist_in_file:
                score += 0.4
            if title_in_file:
                score += 0.6
        
        return score
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        # 移除常见后缀
        patterns = [
            r'\s*\(.*?Live.*?\)',
            r'\s*\(.*?Explicit.*?\)',
            r'\s*\(.*?Remaster.*?\)',
            r'\s*\[.*?\]',
            r'\s*【.*?】',
            r'\s*feat\..*$',
            r'\s*ft\..*$',
            r'\s*official.*?video',
            r'\s*mv',
            r'\s*lyrics',
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        return text.strip()
    
    def suggest_filename(self, metadata: Dict) -> str:
        """生成建议的文件名"""
        artist = metadata.get("artist", "Unknown")
        title = metadata.get("title", "Unknown")
        
        illegal_chars = '<>:"/\\|?*'
        for char in illegal_chars:
            artist = artist.replace(char, "_")
            title = title.replace(char, "_")
        
        return f"{artist} - {title}"
    
    def _clean_filename(self, filename: str) -> str:
        """清理文件名"""
        name = Path(filename).stem if '.' in filename else filename
        
        patterns = [
            r'\s*\(.*?Live.*?\)',
            r'\s*\(.*?Explicit.*?\)',
            r'\s*\(.*?Remaster.*?\)',
            r'\s*\[.*?\]',
            r'\s*【.*?】',
            # ❌ 不要写成 feat\..*$，会删除 feat. 到行尾的所有内容（包括歌名）
            # ✅ 只删除括号/方括号外的 feat. 片段（通常作为后缀）
            r'\s+feat\.\s*[^\-\[\(\]]*?(?=\s*[-\(\[]|$)',
            r'\s+ft\.\s*[^\-\[\(\]]*?(?=\s*[-\(\[]|$)',
            r'\s*official.*?video',
            r'\s*mv',
            r'\s*lyrics',
            r'^\d+\s*[\.\-]\s*',
        ]
        
        for pattern in patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        
        name = name.strip()
        name = re.sub(r'\s+', ' ', name)
        
        return name
    
    def _rate_limit(self):
        """MusicBrainz 速率限制"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()
    
    def calculate_similarity(self, str1: str, str2: str) -> float:
        """计算字符串相似度"""
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


class FileRenamer:
    """文件重命名器"""
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.renamed_files: List[Tuple[str, str]] = []
    
    def rename(self, file_path: str, new_name: str) -> bool:
        """重命名文件"""
        try:
            path = Path(file_path)
            ext = path.suffix
            new_filename = new_name + ext
            new_path = path.parent / new_filename
            
            if path.name == new_filename:
                return True
            
            if new_path.exists():
                counter = 1
                while True:
                    alt_name = f"{new_name}_{counter}{ext}"
                    alt_path = path.parent / alt_name
                    if not alt_path.exists():
                        new_path = alt_path
                        break
                    counter += 1
                    if counter > 100:
                        raise Exception("无法生成唯一文件名")
            
            if not self.dry_run:
                path.rename(new_path)
            
            self.renamed_files.append((str(path), str(new_path)))
            return True
            
        except Exception as e:
            print(f"Rename error for {file_path}: {e}")
            return False
    
    def get_summary(self) -> Dict:
        """获取重命名摘要"""
        return {
            "total": len(self.renamed_files),
            "renamed": self.renamed_files,
            "dry_run": self.dry_run
        }
