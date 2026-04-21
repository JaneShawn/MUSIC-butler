# -*- coding: utf-8 -*-
"""
语言检测器 - 多层保底策略
优先级：网易云API > 歌手关键词 > 歌词内容 > 文件名
"""

import json
import re
from pathlib import Path
from typing import Optional, Tuple


class LanguageDetector:
    """语言检测器"""
    
    # 韩语歌手关键词（必须是完整的、独特的词汇，避免误判）
    # ❌ 不要使用 'rain', 'crush', 'winner' 等常见英文单词
    KOREAN_ARTISTS = {
        # 团体（独特词汇）
        'bts', 'bangtan', 'blackpink', 'twice', 'exo', 'bigbang', 
        'red velvet', 'nct', 'nct 127', 'nct dream', 'aespa',
        'ikon', 'got7', 'monsta x', 'stray kids',
        'seventeen', 'txt', 'tomorrow x together',
        'enhypen', 'ateez', 'treasure', 'the boyz',
        'gfriend', 'mamamoo', 'oh my girl', 'izone', 'itzy', 'stayc', 
        'ive', 'le sserafim', 'newjeans', '(g)i-dle', 'gidle',
        'dreamcatcher', 'everglow', 'loona', 'wjsn', 'cosmic girls',
        
        # 女歌手（独特名字）
        'iu', 'psy', 'gangnam style',
        'taeyeon', 'tiffany young', 'jessica jung', 
        'boa', 'g-dragon', 'gdragon',
        'taeyang', 'daesung', 'seungri', 
        'jennie', 'lisa blackpink', 'rose blackpink', 'jisoo',
        'irene', 'seulgi', 'wendy', 'joy', 'yeri', 
        'karina', 'winter', 'ningning', 'giselle',
        'lee hi', 'akmu', 'akdong musician', 
        'zico', 'heize', 'epik high', 'dynamic duo', 
        'loco', 'jay park', 'gray khann',
        'somi', 'sunmi', 'chung ha', 'hyuna', 'hyuna kim',
        '방탄',
    }
    
    # 日语歌手关键词
    JAPANESE_ARTISTS = {
        'vaundy', 'yonezu kenshi', 'radwimps', 'one ok rock', 'lisa', 'ado',
        'yoasobi', 'official髭男dism', 'back number', 'aimer', 'milet',
        'fujii kaze', 'official hige dandism', 'king gnu', 'yorushika',
        'zutomayo', 'eve', 'reol', 'mafumafu', 'sou', 'flower', 'garnidelia',
    }
    
    # 英语歌手关键词（常见欧美艺人，用于快速判定，避免走到音频检测）
    # 保持精简：只放高知名度、名字独特的艺人
    ENGLISH_ARTISTS = {
        'kanye west', 'taylor swift', 'the weeknd', 'drake', 'kendrick lamar',
        'tyler, the creator', 'tyler the creator', 'j. cole', 'jay-z', 'eminem',
        'ed sheeran', 'bruno mars', 'justin bieber', 'rihanna', 'lady gaga',
        'billie eilish', 'post malone', 'travis scott', 'future', 'lil wayne',
        'coldplay', 'imagine dragons', 'maroon 5', 'one direction',
        'linkin park', 'green day', 'queen', 'the beatles', 'pink floyd',
        'eagles', 'guns n\' roses', 'nirvana', 'metallica', 'ac/dc',
        'ariana grande', 'dualipa', 'doja cat', 'sza', 'beyonce',
        'glass animals', 'lukas graham', 'justin timberlake',
        'prince', 'michael jackson', 'madonna', 'whitney houston',
        'elton john', 'john lennon', 'bob dylan', 'david bowie',
        'frank ocean', 'childish gambino', 'daniel caesar', 'halsey',
        '21 savage', 'camila cabello', 'shawn mendes',
    }
    
    def __init__(self):
        self.cache_file = Path("data/language_detected.json")
        self.cache = self._load_cache()
        
    def _load_cache(self) -> dict:
        """加载缓存"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cache(self):
        """保存缓存"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def detect(self, title: str, artist: str, file_path: str = "") -> Tuple[str, str, float]:
        """
        检测语言
        返回: (语言, 来源, 置信度)
        """
        cache_key = f"{artist}-{title}"
        
        # 最高优先级：检查 LanguageManager 的手动纠正缓存
        # 用户在聊天中标记的语言，扫描时必须尊重，不得覆盖
        manual_lang = self._get_manual_override(cache_key)
        if manual_lang:
            # 同时写入自己的缓存，避免每次扫描都重复读取
            self._save_result(cache_key, title, artist, manual_lang, "manual", 1.0)
            return manual_lang, "manual", 1.0
        
        # 检查自己的缓存
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            # 如果缓存里是 manual，保留；否则正常返回
            return cached['language'], cached['source'], cached['confidence']
        
        # 歌手关键词只在 artist 中匹配，绝不在 title 中匹配
        # 例：Kanye West - Coldest Winter 不应因 title 含 "winter" 而被判韩语
        artist_lower = f" {artist} ".lower()
        title_lower = f" {title} ".lower()
        combined_lower = f" {artist} {title} ".lower()
        
        # 第一层：韩语歌手关键词（仅在 artist 中匹配，避免歌名含常见词被误判）
        for kw in self.KOREAN_ARTISTS:
            kw_lower = kw.lower()
            if f" {kw_lower} " in artist_lower:
                result = ("韩语", "artist_keyword", 0.95)
                self._save_result(cache_key, title, artist, *result)
                return result
        
        # 第二层：日语歌手关键词（仅在 artist 中匹配）
        for kw in self.JAPANESE_ARTISTS:
            kw_lower = kw.lower()
            if f" {kw_lower} " in artist_lower:
                result = ("日语", "artist_keyword", 0.95)
                self._save_result(cache_key, title, artist, *result)
                return result
        
        # 第三层：网易云API获取语言
        netease_lang = self._get_from_netease(title, artist)
        if netease_lang:
            result = (netease_lang, "netease_api", 0.9)
            self._save_result(cache_key, title, artist, *result)
            return result
        
        # 第四层：字符集检测
        char_lang = self._detect_by_chars(title, artist)
        if char_lang:
            result = (char_lang, "char_detect", 0.7)
            self._save_result(cache_key, title, artist, *result)
            return result
        
        # 第五层：英语快速判定（仅基于歌手关键词，歌名纯ASCII不再作为判据）
        # 因为 K-POP / J-POP 大量歌名是纯英文，不能凭歌名判定语言
        english_lang = self._detect_english(artist_lower, artist, title)
        if english_lang:
            result = (english_lang, "english_rule", 0.75)
            self._save_result(cache_key, title, artist, *result)
            return result
        
        # 第六层：音频识别（Whisper分析歌曲内容）
        # ⚠️ 仅作为最后兜底，因为速度极慢且对纯音乐/前奏容易误判
        if file_path and Path(file_path).exists():
            try:
                from core.audio_language_detector import detect_audio_language
                print(f"    [语言检测] 尝试音频识别: {title}")
                audio_lang, audio_conf = detect_audio_language(file_path)
                if audio_lang and audio_conf > 0.75:  # 提高阈值减少误判
                    # 转换语言名称
                    lang_map = {'中文': '国语', 'Korean': '韩语', 'Japanese': '日语'}
                    final_lang = lang_map.get(audio_lang, audio_lang)
                    result = (final_lang, "audio_whisper", audio_conf)
                    self._save_result(cache_key, title, artist, *result)
                    return result
            except Exception as e:
                pass
        
        # 最终默认英语
        result = ("英语", "default", 0.5)
        self._save_result(cache_key, title, artist, *result)
        return result
    
    def _get_from_netease(self, title: str, artist: str) -> Optional[str]:
        """从网易云API获取语言"""
        try:
            import requests
            
            search_url = "https://music.163.com/api/search/get"
            params = {"s": f"{title} {artist}", "type": 1, "offset": 0, "limit": 3}
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://music.163.com/"
            }
            
            resp = requests.get(search_url, params=params, headers=headers, timeout=5)
            data = resp.json()
            
            if not data.get("result") or not data["result"].get("songs"):
                return None
            
            song = data["result"]["songs"][0]
            song_id = song.get("id")
            
            # 获取详情
            detail_url = f"https://music.163.com/api/song/detail?ids=[{song_id}]"
            resp = requests.get(detail_url, headers=headers, timeout=5)
            detail = resp.json()
            
            if detail.get("songs"):
                lang = detail["songs"][0].get("language", "")
                # 转换
                lang_map = {
                    'ZH': '国语', 'zh': '国语',
                    'HK': '粤语', 'hk': '粤语',
                    'EN': '英语', 'en': '英语',
                    'JA': '日语', 'ja': '日语', 'JP': '日语',
                    'KO': '韩语', 'ko': '韩语', 'KR': '韩语',
                }
                return lang_map.get(lang, None)
                
        except Exception as e:
            print(f"  [语言检测] 网易云API失败: {e}")
        
        return None
    
    def _detect_by_chars(self, title: str, artist: str) -> Optional[str]:
        """基于字符集检测"""
        text = f"{artist} {title}"
        
        # 韩语音节
        if any('\uac00' <= c <= '\ud7a3' for c in text):
            return "韩语"
        
        # 日语假名
        if any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' for c in text):
            return "日语"
        
        # 中文字符（无法仅凭字符区分国语/粤语，需结合歌词或歌手信息）
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            # 粤语特有字优先判定
            canto_chars = {'嘅', '系', '唔', '喺', '咁', '啲', '嚟', '乜', '冇', '睇'}
            if any(c in text for c in canto_chars):
                return "粤语"
            return "国语"
        
        return None
    
    def _detect_english(self, artist_lower: str, artist: str, title: str) -> Optional[str]:
        """
        英语快速判定层（仅基于歌手关键词，不基于歌名字符集）
        
        ⚠️ 注意：不通过"纯ASCII歌名"判定语言，因为：
        - K-POP 大量歌名是纯英文（如 NewJeans - Supernatural）
        - 日语歌也有纯英文歌名的情况
        这些如果按ASCII判定会严重误判为英语。
        
        另外，歌手关键词只在 artist_lower 中匹配，绝不在 title 中匹配。
        
        返回 '英语' 或 None（无法确定）
        """
        # 仅通过已知的常见欧美歌手名来判定
        for kw in self.ENGLISH_ARTISTS:
            if f" {kw} " in artist_lower or artist_lower.startswith(f"{kw} ") or artist_lower.endswith(f" {kw}"):
                return "英语"
        
        return None
    
    def _save_result(self, key: str, title: str, artist: str, 
                    language: str, source: str, confidence: float):
        """保存结果"""
        self.cache[key] = {
            'title': title,
            'artist': artist,
            'language': language,
            'source': source,
            'confidence': confidence
        }
        self._save_cache()
    
    def _get_manual_override(self, cache_key: str) -> Optional[str]:
        """
        检查 LanguageManager 的缓存中是否有用户手动纠正。
        这是最高优先级，扫描时不得覆盖。
        """
        try:
            manual_cache_file = Path("data/language_cache.json")
            if not manual_cache_file.exists():
                return None
            with open(manual_cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if cache_key in data:
                entry = data[cache_key]
                if entry.get('source') == 'manual':
                    return entry.get('language')
        except Exception:
            pass
        return None
    
    def manual_set(self, artist: str, title: str, language: str):
        """手动设置"""
        key = f"{artist}-{title}"
        self._save_result(key, title, artist, language, "manual", 1.0)
        print(f"✅ 已设置: {artist} - {title} = {language}")
    
    def get_stats(self) -> dict:
        """获取统计"""
        stats = {}
        for item in self.cache.values():
            lang = item['language']
            stats[lang] = stats.get(lang, 0) + 1
        return dict(sorted(stats.items(), key=lambda x: -x[1]))


# 单例
detector = LanguageDetector()

def detect_language(title: str, artist: str, file_path: str = "") -> Tuple[str, str, float]:
    """便捷函数"""
    return detector.detect(title, artist, file_path)
