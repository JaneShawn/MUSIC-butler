# -*- coding: utf-8 -*-
"""
语言管理器 - 三层检测 + 可编辑文档
1. 网易云API（最准）
2. langdetect自动检测
3. 用户手动纠正
"""

import json
import csv
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class LanguageInfo:
    """歌曲语言信息"""
    file_path: str
    title: str
    artist: str
    language: str  # 英语/国语/粤语/日语/韩语/其他
    source: str    # netease/langdetect/manual/rule
    confidence: float  # 置信度 0-1
    updated_at: str
    notes: str = ""  # 备注/用户注释


class LanguageManager:
    """
    三层语言检测管理器
    """
    
    # 语言代码映射
    LANG_MAP = {
        'en': '英语', 'zh-cn': '国语', 'zh-tw': '国语', 'zh-hk': '粤语',
        'ja': '日语', 'ko': '韩语', 'fr': '法语', 'de': '德语',
        'es': '西班牙语', 'it': '意大利语', 'ru': '俄语', 'other': '其他'
    }
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.cache_file = self.data_dir / "language_cache.json"
        self.csv_file = self.data_dir / "songs_language.csv"
        self.cache: Dict[str, LanguageInfo] = {}
        self._load_cache()
        
        # 尝试导入langdetect
        self.has_langdetect = False
        try:
            from langdetect import detect, DetectorFactory
            DetectorFactory.seed = 0  # 保证可重复
            self.langdetect = detect
            self.has_langdetect = True
        except ImportError:
            print("[WARN] langdetect not installed. Run: pip install langdetect")
    
    def _load_cache(self):
        """加载缓存"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cache = {k: LanguageInfo(**v) for k, v in data.items()}
                print(f"[LanguageManager] Loaded {len(self.cache)} cached entries")
            except Exception as e:
                print(f"[WARN] Failed to load cache: {e}")
    
    def _save_cache(self):
        """保存缓存"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            data = {k: asdict(v) for k, v in self.cache.items()}
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def detect_language(self, file_path: str, title: str, artist: str, 
                       lyrics: Optional[str] = None) -> Tuple[str, str, float]:
        """
        四层语言检测（新增网易云语言标签API）
        返回: (语言, 来源, 置信度)
        """
        cache_key = f"{artist}-{title}"
        
        # 检查是否有用户手动标注
        if cache_key in self.cache:
            info = self.cache[cache_key]
            if info.source == "manual":
                return info.language, "manual", 1.0
        
        # 第一层：网易云语言标签API（最准，不依赖歌词）
        try:
            from core.lyrics_fetcher import LyricsFetcher
            fetcher = LyricsFetcher()
            netease_lang = fetcher.get_language_from_netease(title, artist)
            if netease_lang:
                print(f"    [语言检测] 从网易云API获取: {artist} - {title} = {netease_lang}")
                self._save_to_cache(file_path, title, artist, netease_lang, "netease_api", 0.95)
                return netease_lang, "netease_api", 0.95
        except Exception as e:
            pass
        
        # 第二层：网易云API（通过歌词内容分析）
        if lyrics and len(lyrics) > 50:
            lang, conf = self._detect_by_netease(lyrics)
            if lang and conf > 0.8:
                self._save_to_cache(file_path, title, artist, lang, "netease_lyrics", conf)
                return lang, "netease_lyrics", conf
        
        # 第三层：langdetect自动检测
        if self.has_langdetect:
            lang, conf = self._detect_by_langdetect(title, artist)
            if conf > 0.7:
                self._save_to_cache(file_path, title, artist, lang, "langdetect", conf)
                return lang, "langdetect", conf
        
        # 第四层：规则检测（保底）
        lang, conf = self._detect_by_rules(title, artist)
        self._save_to_cache(file_path, title, artist, lang, "rule", conf)
        return lang, "rule", conf
    
    def _detect_by_netease(self, lyrics: str) -> Tuple[Optional[str], float]:
        """通过歌词内容判断语言（网易云获取的歌词）"""
        # 简单统计：如果有大量假名→日语，有韩语音节→韩语
        ja_chars = sum(1 for c in lyrics if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff')
        ko_chars = sum(1 for c in lyrics if '\uac00' <= c <= '\ud7a3')
        zh_chars = sum(1 for c in lyrics if '\u4e00' <= c <= '\u9fff')
        
        total = len(lyrics)
        if total == 0:
            return None, 0.0
        
        if ja_chars / total > 0.3:
            return "日语", min(0.95, ja_chars / total)
        if ko_chars / total > 0.3:
            return "韩语", min(0.95, ko_chars / total)
        if zh_chars / total > 0.5:
            return "国语", min(0.9, zh_chars / total)
        
        return "英语", 0.6  # 默认
    
    def _detect_by_langdetect(self, title: str, artist: str) -> Tuple[str, float]:
        """使用langdetect检测"""
        try:
            text = f"{title} {artist}".strip()
            if len(text) < 3:
                return "英语", 0.3
            
            detected = self.langdetect(text)
            lang = self.LANG_MAP.get(detected, '其他')
            
            # 置信度估算：langdetect没有直接给出，用文本长度估算
            confidence = min(0.9, 0.5 + len(text) * 0.02)
            
            return lang, confidence
        except Exception as e:
            print(f"[WARN] langdetect failed: {e}")
            return "英语", 0.3
    
    def _detect_by_rules(self, title: str, artist: str) -> Tuple[str, float]:
        """基于规则的检测（保底）"""
        text = f"{artist or ''} {title or ''}"
        text_lower = text.lower()
        
        # 韩语（Unicode音节范围）
        if any('\uac00' <= c <= '\ud7a3' for c in text):
            return "韩语", 0.9
        
        # 日语假名
        if any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' for c in text):
            return "日语", 0.9
        
        # 粤语歌手（完整列表）
        # ⚠️ 仅作为辅助线索，不能仅凭歌手名判定语言（如王菲、邓紫棋有大量国语歌）
        # 只有当歌名中包含明确的粤语特征字时，才结合歌手信息判断
        cantonese_artists = {
            '张学友', '刘德华', '郭富城', '黎明', '张国荣', '梅艳芳', '陈慧娴',
            'beyond', '黄家驹', '陈奕迅', 'eason', '杨千嬅', '谢安琪', '容祖儿',
            '许冠杰', '谭咏麟', '李克勤', '林夕', 'twins', '草蜢',
        }
        has_canto_artist = any(a in text for a in cantonese_artists)
        
        # 中文字符
        zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if zh_count > 0:
            # 粤语特有字（高置信度）
            canto_words = ['嘅', '系', '唔', '喺', '咁', '啲', '嚟', '乜', '冇', '睇']
            if any(w in text for w in canto_words):
                return "粤语", 0.85
            # 如果是知名粤语歌手 + 歌名无明显国语特征，可倾向粤语（但置信度不高）
            if has_canto_artist:
                return "粤语", 0.55  # 低置信度，优先让用户纠正
            return "国语", 0.7
        
        return "英语", 0.5
    
    def _save_to_cache(self, file_path: str, title: str, artist: str, 
                      language: str, source: str, confidence: float):
        """保存到缓存"""
        cache_key = f"{artist}-{title}"
        self.cache[cache_key] = LanguageInfo(
            file_path=file_path,
            title=title,
            artist=artist,
            language=language,
            source=source,
            confidence=confidence,
            updated_at=datetime.now().isoformat()
        )
        self._save_cache()
    
    def manual_correct(self, artist: str, title: str, language: str, notes: str = ""):
        """
        用户手动纠正语言
        使用示例：
            manager.manual_correct("陈奕迅", "富士山下", "粤语", "用户纠正")
        """
        cache_key = f"{artist}-{title}"
        
        if cache_key in self.cache:
            # 更新已有记录
            info = self.cache[cache_key]
            info.language = language
            info.source = "manual"
            info.confidence = 1.0
            info.notes = notes
            info.updated_at = datetime.now().isoformat()
        else:
            # 创建新记录（支持纠正从未检测过的歌）
            self.cache[cache_key] = LanguageInfo(
                file_path="",
                title=title,
                artist=artist,
                language=language,
                source="manual",
                confidence=1.0,
                updated_at=datetime.now().isoformat(),
                notes=notes
            )
        
        self._save_cache()
        print(f"✅ 已手动纠正: {artist} - {title} -> {language}")
        return True
    
    def export_to_csv(self, songs: list) -> str:
        """
        导出歌曲语言信息到CSV（可编辑）
        用户可以用Excel打开编辑后，再导入
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 准备数据
        rows = []
        for song in songs:
            cache_key = f"{song.artist}-{song.title}"
            info = self.cache.get(cache_key)
            
            if info:
                rows.append({
                    'file_path': song.file_path,
                    'artist': song.artist,
                    'title': song.title,
                    'language': info.language,
                    'source': info.source,
                    'confidence': f"{info.confidence:.2f}",
                    'notes': info.notes,
                    'updated_at': info.updated_at
                })
            else:
                # 未检测的歌曲
                rows.append({
                    'file_path': song.file_path,
                    'artist': song.artist,
                    'title': song.title,
                    'language': '未检测',
                    'source': 'none',
                    'confidence': '0.00',
                    'notes': '',
                    'updated_at': ''
                })
        
        # 写入CSV
        with open(self.csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'file_path', 'artist', 'title', 'language', 
                'source', 'confidence', 'notes', 'updated_at'
            ])
            writer.writeheader()
            writer.writerows(rows)
        
        print(f"✅ 已导出 {len(rows)} 首歌曲到: {self.csv_file}")
        print(f"💡 可以用Excel编辑，然后运行 '导入语言文档' 更新")
        return str(self.csv_file)
    
    def import_from_csv(self, csv_path: Optional[str] = None) -> int:
        """
        从CSV导入语言纠正
        返回更新的数量
        """
        csv_path = csv_path or self.csv_file
        if not Path(csv_path).exists():
            print(f"⚠️ 文件不存在: {csv_path}")
            return 0
        
        updated = 0
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 只导入手动修改过的（source=manual或有notes）
                if row.get('source') == 'manual' or row.get('notes'):
                    cache_key = f"{row['artist']}-{row['title']}"
                    self.cache[cache_key] = LanguageInfo(
                        file_path=row['file_path'],
                        title=row['title'],
                        artist=row['artist'],
                        language=row['language'],
                        source='manual',
                        confidence=float(row.get('confidence', 1.0)),
                        notes=row.get('notes', ''),
                        updated_at=datetime.now().isoformat()
                    )
                    updated += 1
        
        self._save_cache()
        print(f"✅ 已导入 {updated} 条手动纠正")
        return updated
    
    def get_stats(self) -> Dict[str, int]:
        """获取语言分布统计"""
        stats = {}
        for info in self.cache.values():
            lang = info.language
            stats[lang] = stats.get(lang, 0) + 1
        return dict(sorted(stats.items(), key=lambda x: -x[1]))


# 单例模式
_language_manager = None

def get_language_manager() -> LanguageManager:
    """获取语言管理器单例"""
    global _language_manager
    if _language_manager is None:
        _language_manager = LanguageManager()
    return _language_manager
