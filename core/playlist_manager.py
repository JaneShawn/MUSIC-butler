"""
Playlist Manager - 智能播放列表生成
支持 foobar2000 兼容的 M3U8 格式
"""
import os
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

try:
    from core.emotion_analyzer import AudioEmotionAnalyzer
except ImportError:
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer


@dataclass
class Playlist:
    """播放列表"""
    name: str
    songs: List[Dict]
    criteria: Dict
    created_at: datetime
    total_duration: float = 0.0
    
    def to_m3u8(self, use_relative_path: bool = True, base_path: Optional[str] = None) -> str:
        """转换为 foobar2000 兼容的 M3U8 格式"""
        lines = ["#EXTM3U", ""]
        
        # 播放列表信息
        lines.append(f"#PLAYLIST:{self.name}")
        lines.append(f"#CREATED:{self.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"#SONGS:{len(self.songs)}")
        if self.criteria.get("description"):
            lines.append(f"#DESCRIPTION:{self.criteria['description']}")
        lines.append("")
        
        for song in self.songs:
            file_path = song.get('file_path', '')
            
            # 路径处理
            if use_relative_path and base_path:
                try:
                    file_path = os.path.relpath(file_path, base_path)
                except ValueError:
                    pass
            
            # 标准化路径分隔符
            file_path = file_path.replace('\\', '/')
            
            # EXTINF 行
            duration = int(song.get('duration', 0))
            artist = song.get('artist', 'Unknown Artist')
            title = song.get('title', 'Unknown Title')
            
            lines.append(f"#EXTINF:{duration},{artist} - {title}")
            lines.append(file_path)
            lines.append("")
        
        return '\n'.join(lines)
    
    def save(self, output_dir: str, use_relative_path: bool = True) -> str:
        """保存播放列表文件"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 文件名处理
        safe_name = "".join(c for c in self.name if c.isalnum() or c in (' ', '-', '_'))
        safe_name = safe_name.strip() or "Playlist"
        filename = f"{safe_name}.m3u8"
        filepath = output_path / filename
        
        m3u8_content = self.to_m3u8(use_relative_path, str(output_path))
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(m3u8_content)
        
        return str(filepath)


class PlaylistGenerator:
    """智能播放列表生成器"""
    
    def __init__(self, librarian, emotion_analyzer=None):
        self.librarian = librarian
        self.emotion_analyzer = emotion_analyzer or AudioEmotionAnalyzer()
    
    def generate(self, criteria: Dict, name: Optional[str] = None) -> Playlist:
        """根据条件生成播放列表"""
        mode = criteria.get('mode', 'shuffle')
        
        if mode == 'shuffle':
            songs = self._mode_shuffle(criteria)
        elif mode == 'smart':
            songs = self._mode_smart(criteria)
        elif mode == 'artist':
            songs = self._mode_artist(criteria)
        elif mode == 'emotion':
            songs = self._mode_emotion(criteria)
        else:
            songs = self._mode_shuffle(criteria)
        
        # 应用时长限制
        songs = self._apply_duration(songs, criteria)
        
        if not name:
            name = self._generate_name(criteria, len(songs))
        
        total_duration = sum(s.get('duration', 240) for s in songs)
        
        return Playlist(
            name=name,
            songs=songs,
            criteria=criteria,
            created_at=datetime.now(),
            total_duration=total_duration
        )
    
    def _song_to_dict(self, song) -> Dict:
        """Song对象转字典"""
        return {
            'file_path': song.file_path,
            'title': song.title or Path(song.file_path).stem,
            'artist': song.artist or 'Unknown',
            'album': song.album or '',
            'duration': 240,  # 默认4分钟
            'genre': song.genre or ''
        }
    
    def _mode_shuffle(self, criteria: Dict) -> List[Dict]:
        """随机模式"""
        songs = [self._song_to_dict(s) for s in self.librarian.songs.values()]
        random.shuffle(songs)
        return songs
    
    def _mode_smart(self, criteria: Dict) -> List[Dict]:
        """智能模式：基于描述搜索"""
        query = criteria.get('query', '随机')
        results = self.librarian.query(query, top_k=50)
        
        songs = []
        for r in results:
            song = r.get('song')
            if song:
                songs.append(self._song_to_dict(song))
        
        # 补充随机歌曲
        if len(songs) < 20:
            existing_paths = {s['file_path'] for s in songs}
            for song in self.librarian.songs.values():
                if song.file_path not in existing_paths:
                    songs.append(self._song_to_dict(song))
                if len(songs) >= 30:
                    break
        
        return songs
    
    def _mode_artist(self, criteria: Dict) -> List[Dict]:
        """艺术家模式"""
        artists = criteria.get('artists', [])
        songs = []
        
        for song in self.librarian.songs.values():
            if song.artist and any(a.lower() in song.artist.lower() for a in artists):
                songs.append(self._song_to_dict(song))
        
        random.shuffle(songs)
        return songs
    
    def _mode_emotion(self, criteria: Dict) -> List[Dict]:
        """情绪模式：优先使用真实情绪标签，fallback到RAG语义搜索"""
        emotion = criteria.get('emotion', 'calm')
        
        # 首先尝试使用真实的情绪标签
        songs_with_emotion = []
        
        if self.emotion_analyzer:
            # 检查哪些歌曲已经被分析过情绪
            for song in self.librarian.songs.values():
                cache_key = self.emotion_analyzer._get_file_hash(song.file_path)
                if cache_key in self.emotion_analyzer._cache:
                    cached = self.emotion_analyzer._cache[cache_key]
                    if cached.get('emotion') == emotion:
                        song_dict = self._song_to_dict(song)
                        song_dict['emotion_confidence'] = cached.get('confidence', 0.5)
                        songs_with_emotion.append(song_dict)
        
        # 如果有足够的真实情绪标签歌曲，直接使用
        if len(songs_with_emotion) >= 10:
            # 按置信度排序
            songs_with_emotion.sort(key=lambda x: x.get('emotion_confidence', 0), reverse=True)
            return songs_with_emotion
        
        # 否则，使用RAG语义搜索作为fallback
        emotion_queries = {
            'happy': '快乐 欢快 开心 轻松 愉悦 正能量',
            'sad': '悲伤 安静 抒情 治愈  melancholy 伤感',
            'energetic': ' energetic 激情 燃 热血 节奏感 强烈',
            'calm': '平静 安静 放松 舒缓 calm peaceful 轻音乐',
            'romantic': '浪漫 甜蜜 温柔 爱情 情歌 心动',
            'nostalgic': '怀旧 经典 回忆 老歌 金曲 岁月',
            'angry': '愤怒 发泄 摇滚 重金属 激烈',
            'focus': '专注 工作 学习 背景音 集中注意力',
            'party': '派对 嗨 舞曲 节奏 热闹 celebration'
        }
        
        query = emotion_queries.get(emotion, emotion)
        
        # 使用 RAG 搜索符合情绪的歌曲
        results = self.librarian.query(query, top_k=50)
        
        songs = []
        seen_paths = {s['file_path'] for s in songs_with_emotion}
        
        for r in results:
            song = r.get('song')
            if song and song.file_path not in seen_paths:
                songs.append(self._song_to_dict(song))
                seen_paths.add(song.file_path)
        
        # 合并两种来源的结果（真实情绪标签优先）
        all_songs = songs_with_emotion + songs
        
        # 如果还不够，补充随机歌曲
        if len(all_songs) < 20:
            for song in self.librarian.songs.values():
                if song.file_path not in seen_paths:
                    all_songs.append(self._song_to_dict(song))
                    if len(all_songs) >= 30:
                        break
        
        return all_songs
    
    def _apply_duration(self, songs: List[Dict], criteria: Dict) -> List[Dict]:
        """应用时长限制"""
        min_minutes = criteria.get('min_duration', 0)
        max_minutes = criteria.get('max_duration', 0)
        
        if min_minutes <= 0 and max_minutes <= 0:
            return songs[:100]  # 默认最多100首
        
        result = []
        total_duration = 0
        
        for song in songs:
            duration_min = song.get('duration', 240) / 60
            
            if max_minutes > 0 and total_duration + duration_min > max_minutes:
                break
            
            result.append(song)
            total_duration += duration_min
            
            if min_minutes > 0 and total_duration >= min_minutes and len(result) >= 10:
                break
        
        return result
    
    def _generate_name(self, criteria: Dict, count: int) -> str:
        """生成播放列表名称"""
        mode = criteria.get('mode', 'shuffle')
        
        # 情绪模式
        if mode == 'emotion':
            emotion_names = {
                'happy': '快乐时光', 'sad': '治愈时刻', 'energetic': '燃向精选',
                'calm': '宁静时光', 'romantic': '浪漫氛围', 'nostalgic': '怀旧金曲',
                'angry': '发泄时刻', 'focus': '专注模式', 'party': '派对嗨歌'
            }
            emotion = criteria.get('emotion', 'calm')
            return f"{emotion_names.get(emotion, emotion)} - {count}首"
        
        elif mode == 'smart' and criteria.get('query'):
            return f"{criteria['query']} - {count}首"
        
        elif mode == 'artist' and criteria.get('artists'):
            return f"{'/'.join(criteria['artists'][:2])}精选 - {count}首"
        
        else:
            return f"随机播放 - {count}首"
