"""
Audio Emotion Analyzer (轻量版)
无需 essentia，使用 pydub + 元数据推断
"""
import os
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class EmotionAnalysisResult:
    """情绪分析结果"""
    emotion: str
    confidence: float
    audio_features: Dict
    lyrics_sentiment: Optional[Dict]
    source: str


class SimpleEmotionAnalyzer:
    """
    轻量级情绪分析器（无需编译）
    
    分析维度：
    1. 音频基础特征（使用pydub）
    2. 文件名/元数据推断
    3. 歌词情感分析
    """
    
    EMOTIONS = {
        'happy': {'name': '快乐', 'keywords': ['happy', 'joy', '快乐', '开心', '欢乐']},
        'sad': {'name': '悲伤', 'keywords': ['sad', 'sorrow', '悲伤', '哭', '泪', ' melancholy']},
        'energetic': {'name': '激情', 'keywords': ['energetic', 'power', '燃', '热血', 'rock', '金属']},
        'calm': {'name': '平静', 'keywords': ['calm', 'peaceful', '安静', '轻音乐', 'sleep', 'sleepy']},
        'romantic': {'name': '浪漫', 'keywords': ['romantic', 'love', '爱', '恋', 'sweet']},
        'nostalgic': {'name': '怀旧', 'keywords': ['nostalgic', 'old', '经典', '回忆', '往日']},
        'angry': {'name': '愤怒', 'keywords': ['angry', 'rage', '怒', '恨', 'rock']},
        'focus': {'name': '专注', 'keywords': ['focus', 'work', '学习', '工作', 'background']},
        'party': {'name': '派对', 'keywords': ['party', 'dance', '舞', '嗨', 'club']},
    }
    
    def __init__(self, kimi_client=None):
        self.kimi = kimi_client
        self._cache_file = Path("data/emotion_cache.json")
        self._cache = self._load_cache()
        
        # 尝试导入 pydub
        self.has_pydub = False
        try:
            from pydub import AudioSegment
            self.AudioSegment = AudioSegment
            self.has_pydub = True
        except ImportError:
            print("[WARN] pydub not installed, audio analysis disabled")
    
    def _load_cache(self) -> Dict:
        if self._cache_file.exists():
            try:
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError, IOError):
                pass
        return {}
    
    def _save_cache(self):
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_file, 'w', encoding='utf-8') as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)
    
    def analyze(self, file_path: str, lyrics: Optional[str] = None, 
                title: Optional[str] = None, artist: Optional[str] = None,
                verbose: bool = False) -> EmotionAnalysisResult:
        """分析歌曲情绪"""
        cache_key = self._get_file_hash(file_path)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if verbose:
                print(f"    [缓存命中] {title or ''} - {cached.get('emotion')}")
            return EmotionAnalysisResult(**cached)
        
        if verbose:
            print(f"    [分析] {title or ''} - {artist or ''}")
        
        # 1. 音频特征（简单版）
        audio_result = self._analyze_audio_simple(file_path) if self.has_pydub else {}
        if verbose and audio_result:
            print(f"      [音频] energy={audio_result.get('energy', 'N/A'):.2f}" if 'energy' in audio_result else "      [音频] 无数据")
        
        # 2. 元数据推断
        meta_result = self._infer_from_metadata(file_path, title, artist)
        if verbose and meta_result:
            print(f"      [元数据] {meta_result.get('emotion', '无')}")
        
        # 3. 无歌词时用 LLM 从歌名+艺术家推断情绪
        llm_meta_result = None
        if not lyrics and self.kimi and title:
            llm_meta_result = self._analyze_metadata_with_llm(title, artist, verbose)

        # 4. 歌词分析
        lyrics_result = self._analyze_lyrics(lyrics, verbose) if lyrics else None
        if verbose:
            if lyrics_result:
                print(f"      [歌词] {lyrics_result.get('emotion')} ({lyrics_result.get('method')})")
            elif llm_meta_result:
                print(f"      [LLM推断] {llm_meta_result.get('emotion')}")
            elif lyrics:
                print(f"      [歌词] 分析失败")
            else:
                print(f"      [歌词] 无歌词")
        
        # 5. 融合决策（LLM 元数据推断权重等同歌词）
        final_emotion, confidence, source = self._fuse_results(audio_result, meta_result, lyrics_result, llm_meta_result)
        
        if verbose:
            print(f"    [结果] {final_emotion} (conf={confidence:.2f}, src={source})")
        
        result = EmotionAnalysisResult(
            emotion=final_emotion,
            confidence=confidence,
            audio_features=audio_result,
            lyrics_sentiment=lyrics_result,
            source=source
        )
        
        self._cache[cache_key] = {
            'emotion': result.emotion,
            'confidence': result.confidence,
            'audio_features': result.audio_features,
            'lyrics_sentiment': result.lyrics_sentiment,
            'source': result.source
        }
        self._save_cache()
        
        return result
    
    def manual_set(self, file_path: str, emotion: str):
        """手动设置歌曲情绪（用户纠正，优先级最高，不会被扫描覆盖）"""
        cache_key = self._get_file_hash(file_path)
        self._cache[cache_key] = {
            'emotion': emotion,
            'confidence': 1.0,
            'audio_features': {},
            'lyrics_sentiment': None,
            'source': 'manual'
        }
        self._save_cache()
    
    def _get_file_hash(self, file_path: str) -> str:
        import hashlib
        try:
            mtime = os.path.getmtime(file_path)
            key = f"{file_path}:{mtime}"
        except OSError:
            key = file_path
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def _analyze_audio_simple(self, file_path: str) -> Dict:
        """使用 pydub 获取简单音频特征"""
        try:
            audio = self.AudioSegment.from_file(file_path)
            
            # 基础信息
            duration_sec = len(audio) / 1000
            
            # 响度（dBFS）
            loudness = audio.dBFS
            
            # 估算能量（通过响度）
            # -20dBFS = 高能量, -40dBFS = 低能量
            energy = max(0, min(1, (loudness + 50) / 30))
            
            # 简单节奏检测（通过检测节拍）
            # 这里用文件大小/时长作为复杂度的代理
            file_size = os.path.getsize(file_path)
            bitrate = (file_size * 8) / duration_sec if duration_sec > 0 else 0
            
            # 假设：高码率 = 更复杂 = 可能更 energetic
            complexity = min(1, bitrate / 1000000)  # 归一化到1Mbps
            
            return {
                'duration': duration_sec,
                'loudness_dbfs': loudness,
                'energy': energy,
                'complexity': complexity,
                'has_pydub': True
            }
        except Exception as e:
            print(f"[WARN] Audio analysis failed: {e}")
            return {'has_pydub': False}
    
    def _infer_from_metadata(self, file_path: str, title: Optional[str], artist: Optional[str]) -> Dict:
        """从文件名和元数据推断情绪"""
        text = " ".join(filter(None, [title, artist, os.path.basename(file_path)])).lower()
        
        scores = {}
        for emotion, data in self.EMOTIONS.items():
            score = sum(1 for kw in data['keywords'] if kw.lower() in text)
            if score > 0:
                scores[emotion] = score
        
        if scores:
            best = max(scores, key=scores.get)
            return {'emotion': best, 'confidence': min(0.7, 0.4 + scores[best] * 0.1)}
        
        return {}
    
    def _analyze_lyrics(self, lyrics: str, verbose: bool = False) -> Optional[Dict]:
        """分析歌词情感"""
        if not lyrics or len(lyrics.strip()) < 10:
            if verbose:
                print(f"      [歌词分析] 歌词太短({len(lyrics) if lyrics else 0}字符)，跳过")
            return None
        
        lyrics = self._clean_lyrics(lyrics)
        
        if verbose:
            print(f"      [歌词分析] 清理后长度: {len(lyrics)}字符")
        
        # 尝试LLM
        if self.kimi:
            try:
                result = self._analyze_lyrics_with_llm(lyrics, verbose)
                if result:
                    return result
            except Exception as e:
                if verbose:
                    print(f"      [歌词分析] LLM失败: {e}")
        elif verbose:
            print("      [歌词分析] Kimi客户端未初始化，跳过LLM")
        
        # Fallback: 关键词
        if verbose:
            print("      [歌词分析] 使用关键词匹配")
        return self._analyze_lyrics_with_keywords(lyrics)
    
    def _clean_lyrics(self, lyrics: str) -> str:
        lyrics = re.sub(r'\[\d{2}:\d{2}\.\d{2,3}\]', '', lyrics)
        lyrics = re.sub(r'\[\w+:[^\]]+\]', '', lyrics)
        return lyrics.strip()
    
    def _analyze_lyrics_with_llm(self, lyrics: str, verbose: bool = False) -> Optional[Dict]:
        # 优化采样：取开头200 + 中间200 + 结尾200，覆盖全曲情绪变化
        lyrics_len = len(lyrics)
        if lyrics_len > 600:
            lyrics_sample = lyrics[:200] + "\n...\n" + lyrics[lyrics_len//2-100:lyrics_len//2+100] + "\n...\n" + lyrics[-200:]
        else:
            lyrics_sample = lyrics
        
        prompt = f"""作为音乐情绪分析师，请判断这首歌的主导情绪。

情绪定义：
- happy(快乐): 欢快、愉悦、正能量、庆祝、甜蜜
- sad(悲伤): 失落、孤独、心碎、忧郁、痛苦、离别
- energetic(激情): 热血、燃、强烈节奏、振奋人心
- calm(平静): 放松、舒缓、冥想、轻音乐、治愈
- romantic(浪漫): 爱情、心动、温柔、亲密
- nostalgic(怀旧): 回忆、时光流逝、老歌、思念
- angry(愤怒): 反抗、不满、激烈、发泄
- focus(专注): 适合工作学习、背景音、不干扰
- party(派对): 嗨、舞曲、夜店、庆祝

歌词样本：
{lyrics_sample}

分析要求：
1. 关注歌词中的情感词汇和主题
2. 即使有少量积极词汇，如果整体基调忧郁，应判定为 sad
3. 不要过度倾向 calm，只有在明确是轻音乐/冥想风格时才选

返回格式：{{"emotion": "情绪类型", "confidence": 0.0-1.0}}
只返回JSON："""
        
        try:
            if verbose:
                print(f"      [LLM分析] 调用API...")
            content = self.kimi.chat([{"role": "user", "content": prompt}])
            if verbose:
                print(f"      [LLM分析] 返回: {content[:100]}...")
            
            if not content:
                if verbose:
                    print(f"      [LLM分析] 返回为空")
                return None
            
            match = re.search(r'\{[^}]+\}', content)
            if match:
                result = json.loads(match.group())
                emotion = result.get('emotion', 'calm')
                confidence = float(result.get('confidence', 0.5))
                if verbose:
                    print(f"      [LLM分析] 结果: {emotion} ({confidence})")
                return {
                    'emotion': emotion,
                    'confidence': confidence,
                    'method': 'llm'
                }
            elif verbose:
                print(f"      [LLM分析] 未找到JSON格式")
        except Exception as e:
            if verbose:
                print(f"      [LLM分析] 异常: {e}")
        
        return None
    
    def _analyze_lyrics_with_keywords(self, lyrics: str) -> Dict:
        lyrics_lower = lyrics.lower()
        
        emotion_keywords = {
            'happy': ['快乐', '开心', '幸福', '笑', '阳光', '美好', '甜蜜', '欢乐', '愉快', '开心', 'smile', 'happy', 'joy', 'laugh', 'sunshine', 'beautiful', 'sweet', 'blessed', 'glad'],
            'sad': [
                # 中文悲伤词
                '泪', '伤', '痛', '失去', '孤独', '寂寞', '分开', '离别', '哭', '心碎', '难过', '痛苦', '悲伤', '绝望', '无助', '空虚', '遗憾', 'miss', '想', '忘不了',
                # 英文悲伤词
                'cry', 'tear', 'sad', 'pain', 'hurt', 'lonely', 'alone', 'broken', 'heart', 'miss', 'regret', 'sorry', 'goodbye', 'farewell', 'lost', 'empty', 'blue', 'melancholy', 'sorrow', 'grief'
            ],
            'energetic': ['奔跑', '飞翔', '力量', '燃烧', '热血', '奋斗', '冲刺', 'power', 'run', 'fly', 'strong', 'fire', 'fight', 'energy', 'powerful'],
            'calm': ['安静', '平静', '宁静', '睡', '梦', '放松', 'peace', 'calm', 'quiet', 'sleep', 'dream', 'relax', 'peaceful', 'gentle'],
            'romantic': ['爱', '心动', '吻', '拥抱', '永远', '喜欢', 'love', 'kiss', 'hug', 'forever', 'heart', 'romantic', ' darling', 'baby'],
            'nostalgic': ['回忆', '过去', '曾经', '旧', '时光', 'memory', 'past', 'remember', 'used to', 'old days', 'time', 'yesterday', 'gone', ' nostalgia'],
            'angry': ['恨', '怒', '火', '爆发', 'angry', 'hate', 'mad', 'rage', 'furious', 'pissed', 'damn', 'fuck', 'hell'],
            'focus': ['努力', '坚持', '梦想', '未来', 'work', 'focus', 'grind', 'hustle', 'dream', 'future', 'goal', 'ambition'],
            'party': ['嗨', '跳', '舞', '喝', 'party', 'dance', 'club', 'drink', 'turn up', 'lit', 'bounce']
        }
        
        scores = {e: sum(1 for kw in kws if kw in lyrics_lower) 
                  for e, kws in emotion_keywords.items()}
        
        if max(scores.values()) == 0:
            return {'emotion': 'calm', 'confidence': 0.3, 'method': 'keyword'}
        
        best = max(scores, key=scores.get)
        return {
            'emotion': best,
            'confidence': min(0.8, 0.4 + scores[best] * 0.1),
            'method': 'keyword'
        }
    
    def _analyze_metadata_with_llm(self, title: str, artist: Optional[str], verbose: bool = False) -> Optional[Dict]:
        """无歌词时，用 Kimi 根据歌名+艺术家推断情绪"""
        if not self.kimi:
            return None
        artist_part = f"歌手: {artist}\n" if artist else ""
        prompt = f"""作为音乐情绪分析师，请仅根据以下信息判断这首歌的主导情绪。

{artist_part}歌名: {title}

情绪选项: happy(快乐), sad(悲伤), energetic(激情), calm(平静), romantic(浪漫), nostalgic(怀旧), angry(愤怒), focus(专注), party(派对)

只返回JSON，不要其他文字。格式: {{"emotion": "...", "confidence": 0.0}}"""
        try:
            content = self.kimi.chat([{"role": "user", "content": prompt}], max_tokens=80)
            if not content:
                return None
            match = re.search(r'\{[^}]+\}', content)
            if match:
                result = json.loads(match.group())
                emotion = result.get('emotion', 'calm')
                if emotion not in self.EMOTIONS:
                    emotion = 'calm'
                return {'emotion': emotion, 'confidence': float(result.get('confidence', 0.6)), 'method': 'llm_meta'}
        except Exception:
            pass
        return None

    def _fuse_results(self, audio: Dict, meta: Dict, lyrics: Optional[Dict], llm_meta: Optional[Dict] = None) -> Tuple[str, float, str]:
        """融合多维度结果 - 歌词主导"""
        # 如果歌词分析有高置信度结果，优先采用
        if lyrics and 'emotion' in lyrics:
            lyrics_conf = lyrics.get('confidence', 0.5)
            lyrics_emotion = lyrics['emotion']
            
            # 歌词置信度 > 0.7 时，歌词权重提升到 70%
            if lyrics_conf > 0.7:
                return lyrics_emotion, min(0.9, lyrics_conf), 'lyrics_dominate'
            
            # 歌词置信度 > 0.5 时，歌词权重 50%
            if lyrics_conf > 0.5:
                candidates = {lyrics_emotion: 0.5}
                # 其他维度作为辅助
                if audio and 'energy' in audio:
                    energy = audio['energy']
                    if energy > 0.7 and lyrics_emotion != 'energetic':
                        candidates['energetic'] = candidates.get('energetic', 0) + 0.25
                    elif energy < 0.3 and lyrics_emotion not in ['calm', 'sad']:
                        candidates['calm'] = candidates.get('calm', 0) + 0.25
                
                best = max(candidates, key=candidates.get)
                return best, min(0.85, candidates[best]), 'lyrics_weighted'
        
        # 传统融合（歌词置信度低或无时）
        candidates = {}
        
        # 音频权重 20%
        if audio and 'energy' in audio:
            energy = audio['energy']
            if energy > 0.7:
                candidates['energetic'] = candidates.get('energetic', 0) + 0.20
            elif energy < 0.3:
                candidates['calm'] = candidates.get('calm', 0) + 0.20
        
        # 元数据权重 25%
        if meta and 'emotion' in meta:
            candidates[meta['emotion']] = candidates.get(meta['emotion'], 0) + 0.25
        
        # 歌词权重 35%（低置信度）
        if lyrics and 'emotion' in lyrics:
            candidates[lyrics['emotion']] = candidates.get(lyrics['emotion'], 0) + 0.35
        
        if candidates:
            best = max(candidates, key=candidates.get)
            return best, min(0.8, candidates[best]), 'fusion'
        
        # 没有有效输入时，根据音频特征推断
        if audio and 'energy' in audio:
            energy = audio['energy']
            if energy > 0.6:
                return 'energetic', 0.5, 'audio_fallback'
            elif energy < 0.4:
                return 'calm', 0.5, 'audio_fallback'
        
        # 最后fallback，但降低置信度
        return 'calm', 0.3, 'default'
    
    def batch_analyze(self, songs: List[Dict], progress_callback=None, verbose: bool = False) -> Dict[str, EmotionAnalysisResult]:
        """批量分析（自动从专用歌词目录读取）"""
        # 尝试从专用歌词目录读取歌词
        lyrics_dir = Path("data/lyrics")
        
        results = {}
        for i, song in enumerate(songs):
            try:
                file_path = song.get('file_path')
                title = song.get('title', '')
                artist = song.get('artist', '')
                lyrics = song.get('lyrics')
                
                # 如果没有传入歌词，尝试从专用目录读取
                if not lyrics and lyrics_dir.exists():
                    # 尝试 "艺术家 - 标题.lrc"
                    safe_name = f"{artist} - {title}".replace('<', '_').replace('>', '_').replace(':', '_').replace('"', '_').replace('/', '_').replace('\\', '_').replace('|', '_').replace('?', '_').replace('*', '_')
                    lrc_path = lyrics_dir / f"{safe_name}.lrc"
                    if lrc_path.exists():
                        lyrics = lrc_path.read_text(encoding='utf-8')
                        if verbose:
                            print(f"  [歌词] 从目录读取: {title}")
                    else:
                        # 尝试只用标题
                        safe_title = title.replace('<', '_').replace('>', '_').replace(':', '_').replace('"', '_').replace('/', '_').replace('\\', '_').replace('|', '_').replace('?', '_').replace('*', '_')
                        lrc_path2 = lyrics_dir / f"{safe_title}.lrc"
                        if lrc_path2.exists():
                            lyrics = lrc_path2.read_text(encoding='utf-8')
                            if verbose:
                                print(f"  [歌词] 从目录读取(仅标题): {title}")
                
                if verbose and not lyrics:
                    print(f"  [歌词] 未找到: {title}")
                
                result = self.analyze(file_path, lyrics, title, artist, verbose=verbose)
                results[file_path] = result
            except Exception as e:
                print(f"[ERROR] {song.get('file_path')}: {e}")
                results[song.get('file_path')] = EmotionAnalysisResult('calm', 0.0, {}, None, 'error')
            
            if progress_callback:
                progress_callback(i + 1, len(songs))
        
        return results
