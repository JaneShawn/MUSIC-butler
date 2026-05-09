"""
Single source of truth for language codes and aliases used across the codebase.
Import from here instead of duplicating dicts in chat_unified, language_manager, audio_language_detector, etc.
"""

# ISO/language-detection code → Chinese display name
LANG_CODE_TO_NAME = {
    "en": "英语", "eng": "英语",
    "zh-cn": "国语", "zh-tw": "国语", "zh": "国语",
    "zh-hk": "粤语", "yue": "粤语",
    "ja": "日语", "jpn": "日语",
    "ko": "韩语", "kor": "韩语",
    "fr": "法语", "fra": "法语",
    "de": "德语", "deu": "德语",
    "es": "西班牙语", "spa": "西班牙语",
    "it": "意大利语", "ita": "意大利语",
    "ru": "俄语", "rus": "俄语",
    "other": "其他",
}

# User-facing alias → canonical Chinese name (what the DB stores)
# This is the most important map — resolves "英文" → "英语", "中文" → "国语", etc.
LANGUAGE_ALIAS = {
    # English
    "英文": "英语", "英语": "英语", "eng": "英语", "english": "英语",
    # Chinese → Mandarin
    "中文": "国语", "华语": "国语", "国语": "国语", "普通话": "国语", "chinese": "国语",
    # Cantonese
    "粤语": "粤语", "广东话": "粤语", "cantonese": "粤语",
    # Japanese
    "日语": "日语", "日文": "日语", "japanese": "日语",
    # Korean
    "韩语": "韩语", "韩文": "韩语", "朝鲜语": "韩语", "korean": "韩语",
    # French
    "法语": "法语", "法文": "法语", "french": "法语",
    # German
    "德语": "德语", "德文": "德语", "german": "德语",
    # Spanish
    "西班牙语": "西班牙语", "西语": "西班牙语", "spanish": "西班牙语",
    # Italian
    "意大利语": "意大利语", "italian": "意大利语",
    # Russian
    "俄语": "俄语", "俄文": "俄语", "russian": "俄语",
}

# Whitelist of canonical language names stored in DB
CANONICAL_LANGUAGES = {"英语", "国语", "粤语", "日语", "韩语", "法语", "德语", "西班牙语", "意大利语", "俄语", "其他"}

# Whisper language code → Chinese name (subset used by audio_language_detector)
WHISPER_LANG_MAP = {
    "en": "英语", "zh": "国语", "yue": "粤语", "ja": "日语",
    "ko": "韩语", "fr": "法语", "de": "德语", "es": "西班牙语",
}


def resolve_language(raw: str) -> str:
    """Resolve any language alias to canonical name. Returns original if unknown."""
    return LANGUAGE_ALIAS.get(raw, raw)


def resolve_emotion(raw: str) -> str:
    """Resolve any emotion alias to canonical English name."""
    from core.emotion_constants import EMOTION_ALIAS
    return EMOTION_ALIAS.get(raw, raw)
