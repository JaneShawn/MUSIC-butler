# -*- coding: utf-8 -*-
"""
音频语言检测器 - 基于Whisper快速语言检测（非转录）

⚠️ 性能警告：
- 本模块仅作为最后兜底使用（LanguageDetector 的第六层）
- 对纯音乐/前奏/电子音效容易误判，结果仅供参考
- 如需准确结果，请优先使用文本检测或网易云API
"""

import json
import numpy as np
from pathlib import Path
from typing import Optional, Tuple


class AudioLanguageDetector:
    """
    音频语言检测器（极速版）
    
    使用 Whisper 的 detect_language() 方法：
    - 只提取前 30 秒音频
    - 只跑 Encoder + 一个 Language Token 预测
    - 不跑 Decoder，不生成文本，速度比 transcribe() 快 30~50 倍
    """
    
    # Whisper语言代码映射
    WHISPER_LANG_MAP = {
        'en': '英语', 'zh': '中文', 'de': '德语', 'es': '西班牙语',
        'fr': '法语', 'it': '意大利语', 'ja': '日语', 'ko': '韩语',
        'pt': '葡萄牙语', 'ru': '俄语', 'nl': '荷兰语', 'pl': '波兰语',
        'ar': '阿拉伯语', 'hi': '印地语', 'vi': '越南语', 'tr': '土耳其语',
        'id': '印尼语', 'th': '泰语', 'sv': '瑞典语', 'cs': '捷克语',
        'el': '希腊语', 'he': '希伯来语', 'ro': '罗马尼亚语', 'hu': '匈牙利语',
    }
    
    def __init__(self):
        self.cache_file = Path("data/audio_language_cache.json")
        self.cache = self._load_cache()
        self.model = None  # 延迟加载
        
    def _load_cache(self) -> dict:
        """加载缓存"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError, IOError):
                pass
        return {}

    def _save_cache(self):
        """保存缓存"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def _load_model(self):
        """延迟加载Whisper模型"""
        if self.model is None:
            try:
                import whisper
                print("  [音频语言检测] 加载Whisper模型...")
                # 使用 tiny 模型（语言检测对模型质量要求不高，速度优先）
                self.model = whisper.load_model("tiny")
            except Exception as e:
                print(f"  [WARN] Whisper加载失败: {e}")
                return False
        return True
    
    def detect(self, audio_file: str) -> Tuple[Optional[str], float]:
        """
        检测音频文件的语言（极速版）
        
        流程：
        1. 加载前 30 秒音频
        2. 计算 log-mel spectrogram
        3. 调用 model.detect_language()（只跑encoder）
        4. 取概率最高的语言
        
        返回: (语言, 置信度)
        """
        # 检查缓存
        if audio_file in self.cache:
            cached = self.cache[audio_file]
            return cached['language'], cached['confidence']
        
        # 加载模型
        if not self._load_model():
            return None, 0.0
        
        try:
            import whisper
            
            print(f"  [音频语言检测] 分析: {Path(audio_file).name}")
            
            # 1. 加载音频，只保留前30秒（采样率16kHz）
            audio = whisper.load_audio(str(audio_file))
            audio = whisper.pad_or_trim(audio, length=30 * 16000)  # 30秒
            
            # 2. 计算 mel spectrogram
            mel = whisper.log_mel_spectrogram(audio).to(self.model.device)
            
            # 3. 检测语言（只跑 encoder，不跑 decoder，极快）
            # 返回: (tokenizer, {lang_code: probability})
            _, probs = self.model.detect_language(mel)
            
            # 取概率最高的语言
            detected_lang = max(probs, key=probs.get)
            confidence = float(probs[detected_lang])
            
            language = self.WHISPER_LANG_MAP.get(detected_lang, detected_lang)
            
            # 保存缓存
            self.cache[audio_file] = {
                'language': language,
                'confidence': confidence,
                'whisper_code': detected_lang
            }
            self._save_cache()
            
            print(f"  [音频语言检测] 结果: {language} ({confidence:.2f})")
            return language, confidence
            
        except Exception as e:
            print(f"  [WARN] 音频语言检测失败: {e}")
            return None, 0.0
    
    def detect_batch(self, audio_files: list, progress_callback=None) -> dict:
        """批量检测"""
        results = {}
        for i, file_path in enumerate(audio_files):
            lang, conf = self.detect(file_path)
            if lang:
                results[file_path] = {'language': lang, 'confidence': conf}
            if progress_callback:
                progress_callback(i + 1, len(audio_files))
        return results


# 便捷函数
def detect_audio_language(audio_file: str) -> Tuple[Optional[str], float]:
    """检测单个音频文件的语言"""
    detector = AudioLanguageDetector()
    return detector.detect(audio_file)
