"""
Audio Emotion Analyzer - 音频情绪分析器
结合音频特征 + 歌词情感分析
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json


@dataclass
class EmotionAnalysisResult:
    """情绪分析结果"""
    emotion: str  # 主要情绪
    confidence: float  # 置信度 0-1
    audio_features: Dict  # 音频特征详情
    lyrics_sentiment: Optional[Dict]  # 歌词情感分析
    source: str  # 判断来源: audio/lyrics/both


class AudioEmotionAnalyzer:
    """
    音频情绪分析器
    
    分析维度：
    1. 音频特征（BPM、Energy、音高等）
    2. 歌词情感（使用LLM或本地模型）
    """
    
    # 情绪定义
    EMOTIONS = {
        'happy': {'valence': (0.6, 1.0), 'energy': (0.5, 1.0), 'name': '快乐'},
        'sad': {'valence': (0.0, 0.4), 'energy': (0.0, 0.5), 'name': '悲伤'},
        'energetic': {'valence': (0.4, 1.0), 'energy': (0.7, 1.0), 'name': '激情'},
        'calm': {'valence': (0.3, 0.7), 'energy': (0.0, 0.4), 'name': '平静'},
        'romantic': {'valence': (0.5, 0.9), 'energy': (0.2, 0.6), 'name': '浪漫'},
        'nostalgic': {'valence': (0.3, 0.6), 'energy': (0.2, 0.5), 'name': '怀旧'},
        'angry': {'valence': (0.0, 0.4), 'energy': (0.7, 1.0), 'name': '愤怒'},
        'focus': {'valence': (0.3, 0.8), 'energy': (0.1, 0.5), 'name': '专注'},
        'party': {'valence': (0.5, 1.0), 'energy': (0.8, 1.0), 'name': '派对'},
    }
    
    def __init__(self, kimi_client=None):
        self.kimi = kimi_client
        self._cache_file = Path("data/emotion_cache.json")
        self._cache = self._load_cache()
        
        # 尝试导入 essentia
        self.has_essentia = False
        try:
            import essentia.standard as es
            self.es = es
            self.has_essentia = True
        except ImportError:
            print("[WARN] essentia not installed, audio analysis disabled")
            print("       Install with: pip install essentia")
    
    def _load_cache(self) -> Dict:
        """加载情绪缓存"""
        if self._cache_file.exists():
            try:
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cache(self):
        """保存情绪缓存"""
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_file, 'w', encoding='utf-8') as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)
    
    def analyze(self, file_path: str, lyrics: Optional[str] = None) -> EmotionAnalysisResult:
        """
        分析歌曲情绪
        
        Args:
            file_path: 音频文件路径
            lyrics: 歌词文本（可选）
        
        Returns:
            EmotionAnalysisResult: 情绪分析结果
        """
        # 检查缓存
        cache_key = self._get_file_hash(file_path)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return EmotionAnalysisResult(**cached)
        
        # 1. 音频特征分析
        audio_result = self._analyze_audio_features(file_path) if self.has_essentia else None
        
        # 2. 歌词情感分析
        lyrics_result = self._analyze_lyrics(lyrics) if lyrics else None
        
        # 3. 融合决策
        final_emotion, confidence, source = self._fuse_results(audio_result, lyrics_result)
        
        result = EmotionAnalysisResult(
            emotion=final_emotion,
            confidence=confidence,
            audio_features=audio_result or {},
            lyrics_sentiment=lyrics_result,
            source=source
        )
        
        # 缓存结果
        self._cache[cache_key] = {
            'emotion': result.emotion,
            'confidence': result.confidence,
            'audio_features': result.audio_features,
            'lyrics_sentiment': result.lyrics_sentiment,
            'source': result.source
        }
        self._save_cache()
        
        return result
    
    def _get_file_hash(self, file_path: str) -> str:
        """获取文件标识（用于缓存）"""
        import hashlib
        # 使用文件路径 + 修改时间作为key
        mtime = os.path.getmtime(file_path)
        return hashlib.md5(f"{file_path}:{mtime}".encode()).hexdigest()[:16]
    
    def _analyze_audio_features(self, file_path: str) -> Optional[Dict]:
        """
        使用 Essentia 提取音频特征
        """
        if not self.has_essentia:
            return None
        
        try:
            # 加载音频
            loader = self.es.MonoLoader(filename=file_path)
            audio = loader()
            
            # 提取特征
            # 1. BPM (节奏)
            rhythm_extractor = self.es.RhythmExtractor2013()
            bpm, _, _, _ = rhythm_extractor(audio)
            
            # 2. Energy (能量)
            energy = self.es.Energy()(audio)
            
            # 3. Loudness (响度)
            loudness = self.es.Loudness()(audio)
            
            # 4. 音高相关 (用于判断valence)
            pitch_extractor = self.es.PredominantPitchMelodia()
            pitch, _ = pitch_extractor(audio)
            pitch_mean = sum(pitch) / len(pitch) if len(pitch) > 0 else 0
            
            # 5. Danceability (舞曲性)
            danceability = self.es.Danceability()(audio)
            
            # 6. 频谱特征
            spectral_centroid = self.es.SpectralCentroidTime()(audio)
            
            # 归一化到 0-1 范围
            # BPM: 60-180 -> 0-1
            bpm_norm = max(0, min(1, (bpm - 60) / 120))
            # Energy: 通常已经在合理范围，做简单归一化
            energy_norm = min(1, energy * 10) if energy < 0.1 else min(1, energy)
            
            return {
                'bpm': float(bpm),
                'bpm_normalized': float(bpm_norm),
                'energy': float(energy),
                'energy_normalized': float(energy_norm),
                'loudness': float(loudness),
                'pitch_mean': float(pitch_mean),
                'danceability': float(danceability),
                'spectral_centroid': float(spectral_centroid)
            }
            
        except Exception as e:
            print(f"[WARN] Audio analysis failed for {file_path}: {e}")
            return None
    
    def _analyze_lyrics(self, lyrics: str) -> Optional[Dict]:
        """
        分析歌词情感
        
        策略：
        1. 使用LLM进行情感分析（如果可用）
        2. 或使用简单关键词匹配（fallback）
        """
        if not lyrics or len(lyrics.strip()) < 10:
            return None
        
        # 清理歌词
        lyrics = self._clean_lyrics(lyrics)
        
        # 尝试使用LLM分析
        if self.kimi:
            try:
                return self._analyze_lyrics_with_llm(lyrics)
            except Exception as e:
                print(f"[WARN] LLM lyrics analysis failed: {e}")
        
        # Fallback: 关键词匹配
        return self._analyze_lyrics_with_keywords(lyrics)
    
    def _clean_lyrics(self, lyrics: str) -> str:
        """清理歌词文本"""
        # 移除时间戳 [00:12.34]
        lyrics = re.sub(r'\[\d{2}:\d{2}\.\d{2,3}\]', '', lyrics)
        # 移除元标签 [ar:艺术家]
        lyrics = re.sub(r'\[\w+:[^\]]+\]', '', lyrics)
        # 移除空行
        lyrics = '\n'.join(line.strip() for line in lyrics.split('\n') if line.strip())
        return lyrics
    
    def _analyze_lyrics_with_llm(self, lyrics: str) -> Dict:
        """使用LLM分析歌词情感"""
        # 只取前500字（控制成本）
        lyrics_sample = lyrics[:500] if len(lyrics) > 500 else lyrics
        
        prompt = f"""分析以下歌词的情感，以JSON格式返回：

歌词：
{lyrics_sample}

请分析：
1. sentiment: positive(积极) / negative(消极) / neutral(中性)
2. emotion: happy(快乐) / sad(悲伤) / energetic(激情) / calm(平静) / romantic(浪漫) / nostalgic(怀旧) / angry(愤怒)
3. confidence: 0-1的置信度
4. keywords: 情绪关键词列表（3-5个）

只返回JSON，不要其他内容：
{{
  "sentiment": "positive",
  "emotion": "happy", 
  "confidence": 0.85,
  "keywords": ["阳光", "微笑", "快乐"]
}}"""
        
        response = self.kimi.chat([{"role": "user", "content": prompt}])
        
        # response 是字符串，清理可能的 markdown 代码块
        content = response.strip() if response else ""
        if content.startswith("```json"):
            content = content[7:].strip()
        if content.startswith("```"):
            content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
        
        # 提取JSON
        try:
            # 尝试直接解析
            result = json.loads(content)
        except json.JSONDecodeError:
            # 尝试从文本中提取JSON（支持嵌套和换行）
            match = re.search(r'\{[\s\S]*?\}', content)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    raise ValueError("Invalid LLM response format")
            else:
                raise ValueError("Invalid LLM response format")
        
        return {
            'sentiment': result.get('sentiment', 'neutral'),
            'emotion': result.get('emotion', 'calm'),
            'confidence': float(result.get('confidence', 0.5)),
            'keywords': result.get('keywords', [])
        }
    
    def _analyze_lyrics_with_keywords(self, lyrics: str) -> Dict:
        """使用关键词匹配分析歌词情感（Fallback）"""
        lyrics_lower = lyrics.lower()
        
        # 情绪关键词词典
        # ⚠️ 不同情绪的关键词应当尽量互斥，避免同一首歌被多个情绪高分匹配
        emotion_keywords = {
            'happy': ['快乐', '开心', '幸福', '笑', '阳光', '美好', '甜蜜', '欢乐', '愉悦', '灿烂', '欢喜'],
            'sad': ['泪', '伤心', '痛苦', '失去', '孤独', '寂寞', '分开', '离别', '心碎', '难过', '悲伤', '哭泣', '绝望', '无助'],
            'energetic': ['奔跑', '飞翔', '力量', '燃烧', '热血', '战斗', '冲刺', '突破', '挑战', '激昂', '澎湃'],
            'calm': ['安静', '平静', '宁静', '沉睡', '梦境', '微风', '海风', '云朵', '轻柔', '淡然', '冥想', '舒缓'],
            'romantic': ['心动', '亲吻', '拥抱', '永远', '誓言', '浪漫', '恋情', '情人', '相爱', '眷恋', '痴情'],
            'nostalgic': ['回忆', '过去', '曾经', '旧日', '老旧', '时光', '岁月', '童年', '青春', '往事', '怀念'],
            'angry': ['仇恨', '愤怒', '怒火', '爆发', '反抗', '撕裂', '毁灭', '不服', '抗争', '狂暴'],
        }
        
        # 统计各情绪匹配数
        scores = {}
        for emotion, keywords in emotion_keywords.items():
            score = sum(1 for kw in keywords if kw in lyrics_lower)
            scores[emotion] = score
        
        # 找出最高分的情绪
        if max(scores.values()) == 0:
            return {'sentiment': 'neutral', 'emotion': 'calm', 'confidence': 0.3, 'keywords': []}
        
        best_emotion = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = scores[best_emotion] / total if total > 0 else 0.3
        
        # 确定sentiment
        sentiment_map = {
            'happy': 'positive', 'energetic': 'positive', 'romantic': 'positive',
            'sad': 'negative', 'angry': 'negative',
            'calm': 'neutral', 'nostalgic': 'neutral'
        }
        
        return {
            'sentiment': sentiment_map.get(best_emotion, 'neutral'),
            'emotion': best_emotion,
            'confidence': min(0.8, confidence),  # 关键词方法上限0.8
            'keywords': [kw for kw in emotion_keywords[best_emotion] if kw in lyrics_lower][:5]
        }
    
    def _fuse_results(self, audio_result: Optional[Dict], lyrics_result: Optional[Dict]) -> Tuple[str, float, str]:
        """
        融合音频和歌词分析结果
        
        策略：
        1. 都有结果时：加权平均，音频60% + 歌词40%
        2. 只有音频：纯音频判断
        3. 只有歌词：纯歌词判断
        """
        if audio_result and lyrics_result:
            # 都有结果，融合
            audio_emotion = self._emotion_from_audio(audio_result)
            lyrics_emotion = lyrics_result['emotion']
            
            # 如果一致，高置信度
            if audio_emotion == lyrics_emotion:
                return audio_emotion, 0.9, 'both'
            
            # 如果不一致，优先音频（音乐本身比歌词更直接表达情绪）
            # 但降低置信度
            return audio_emotion, 0.6, 'both_mismatch'
        
        elif audio_result:
            # 只有音频
            emotion = self._emotion_from_audio(audio_result)
            return emotion, 0.7, 'audio'
        
        elif lyrics_result:
            # 只有歌词
            emotion = lyrics_result['emotion']
            confidence = lyrics_result['confidence']
            return emotion, confidence, 'lyrics'
        
        else:
            # 都没有，默认
            return 'calm', 0.3, 'default'
    
    def _emotion_from_audio(self, features: Dict) -> str:
        """
        根据音频特征判断情绪
        
        使用valence-energy二维模型
        """
        # 计算valence（音高积极性）
        # 高pitch = 更积极
        valence = min(1, max(0, features.get('pitch_mean', 200) / 400))
        
        # Energy 直接使用
        energy = features.get('energy_normalized', 0.5)
        
        # 在9种情绪中找到最接近的
        best_match = 'calm'
        min_distance = float('inf')
        
        for emotion, ranges in self.EMOTIONS.items():
            valence_center = (ranges['valence'][0] + ranges['valence'][1]) / 2
            energy_center = (ranges['energy'][0] + ranges['energy'][1]) / 2
            
            distance = ((valence - valence_center) ** 2 + (energy - energy_center) ** 2) ** 0.5
            
            if distance < min_distance:
                min_distance = distance
                best_match = emotion
        
        return best_match
    
    def batch_analyze(self, songs: List[Dict], progress_callback=None) -> Dict[str, EmotionAnalysisResult]:
        """
        批量分析歌曲情绪
        
        Args:
            songs: [{'file_path': ..., 'lyrics': ...}, ...]
            progress_callback: 进度回调函数 (current, total)
        
        Returns:
            Dict[file_path, EmotionAnalysisResult]
        """
        results = {}
        total = len(songs)
        
        for i, song in enumerate(songs):
            file_path = song.get('file_path')
            lyrics = song.get('lyrics')
            
            try:
                result = self.analyze(file_path, lyrics)
                results[file_path] = result
            except Exception as e:
                print(f"[ERROR] Failed to analyze {file_path}: {e}")
                results[file_path] = EmotionAnalysisResult('calm', 0.0, {}, None, 'error')
            
            if progress_callback:
                progress_callback(i + 1, total)
        
        return results
