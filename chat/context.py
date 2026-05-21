# -*- coding: utf-8 -*-
"""
Chat Context - NLP 工具类
ContextManager 已由 LangGraph MemorySaver 替代，此文件只保留 NLPUtils。
"""
from core.emotion_constants import EMOTION_KEYWORDS, MOOD_KEYWORDS


class NLPUtils:
    """NLP 工具类 - 处理中文文本的边界情况"""

    STOP_WORDS = {
        '的', '了', '吗', '呢', '吧', '啊', '哦', '嗯', '呗', '嘛',
        '是', '有', '在', '和', '与', '或', '这', '那', '它', '个',
    }

    SONG_SUFFIXES = [
        '这首歌的', '这首的', '这个的', '这首歌', '这首', '这个',
        '的歌曲', '的歌', '之歌', '版本', '版',
    ]

    ARTIST_SUFFIXES = [
        '唱的歌', '唱的', '的作品', '的歌', '的',
    ]

    EMOTION_KEYWORDS = EMOTION_KEYWORDS
    MOOD_KEYWORDS = MOOD_KEYWORDS

    @classmethod
    def clean_song_name(cls, text: str) -> str:
        if not text:
            return text
        original = text.strip()
        if len(original) <= 2:
            return original
        cleaned = original
        while cleaned and len(cleaned) > 2 and cleaned[0] in cls.STOP_WORDS:
            cleaned = cleaned[1:].strip()
        while cleaned and len(cleaned) > 2 and cleaned[-1] in cls.STOP_WORDS:
            cleaned = cleaned[:-1].strip()
        for suffix in cls.SONG_SUFFIXES:
            if cleaned.endswith(suffix) and len(cleaned) - len(suffix) >= 2:
                cleaned = cleaned[:-len(suffix)].strip()
                break
        while cleaned and len(cleaned) > 2 and cleaned[0] in cls.STOP_WORDS:
            cleaned = cleaned[1:].strip()
        while cleaned and len(cleaned) > 2 and cleaned[-1] in cls.STOP_WORDS:
            cleaned = cleaned[:-1].strip()
        if len(cleaned) < 2 or len(cleaned) < len(original) * 0.3:
            return original
        return cleaned

    @classmethod
    def clean_artist_name(cls, text: str) -> str:
        if not text:
            return text
        text = text.strip()
        for suffix in sorted(cls.ARTIST_SUFFIXES, key=len, reverse=True):
            if text.endswith(suffix):
                text = text[:-len(suffix)].strip()
                break
        return text

    @classmethod
    def normalize_input(cls, text: str) -> str:
        if not text:
            return text
        text = ' '.join(text.split())
        text = text.replace('，', ',').replace('。', '.').replace('？', '?').replace('！', '!')
        text = text.strip('.,!?;:，。！？；：')
        return text.strip()
