"""
Single source of truth for emotion/mood keywords used across the codebase.
Import from here instead of duplicating dicts in chat_unified, context, playlist_engine, etc.
"""

# Chinese keyword → canonical English emotion
EMOTION_KEYWORDS = {
    "快乐": "happy", "开心": "happy", "欢快": "happy", "高兴": "happy",
    "悲伤": "sad", "难过": "sad", "伤感": "sad", "抒情": "sad",
    "治愈": "calm", "安静": "calm", "平静": "calm", "放松": "calm", "舒缓": "calm", "轻松": "calm", "冥想": "calm",
    "燃": "energetic", "激情": "energetic", "热血": "energetic", "运动": "energetic", "嗨": "energetic",
    "浪漫": "romantic", "甜蜜": "romantic", "爱情": "romantic", "心动": "romantic",
    "怀旧": "nostalgic", "经典": "nostalgic", "回忆": "nostalgic", "老歌": "nostalgic",
    "愤怒": "angry", "发泄": "angry", "摇滚": "angry",
    "专注": "focus", "工作": "focus", "学习": "focus",
    "派对": "party", "聚会": "party", "舞曲": "party",
}

# English canonical → Chinese display name
EMOTION_NAMES = {
    "happy": "开心",
    "sad": "悲伤",
    "calm": "安静",
    "energetic": "激情",
    "romantic": "浪漫",
    "nostalgic": "怀旧",
    "angry": "愤怒",
    "focus": "专注",
    "party": "派对",
}

# Full emotion alias map (Chinese + English → canonical English)
EMOTION_ALIAS = dict(EMOTION_KEYWORDS)
for eng_name in EMOTION_NAMES:
    EMOTION_ALIAS[eng_name] = eng_name

# Mood/scenario keywords for music discovery (NetEase playlists)
MOOD_KEYWORDS = {
    "工作": "work", "办公": "work", "专注": "work",
    "学习": "study", "自习": "study",
    "运动": "workout", "健身": "workout", "跑步": "workout",
    "放松": "relax", "休息": "relax", "休闲": "relax",
    "睡觉": "sleep", "睡眠": "sleep", "助眠": "sleep",
    "派对": "party", "聚会": "party", "嗨": "party",
    "通勤": "commute", "路上": "commute", "开车": "commute",
}

# Speed/tempo keyword → emotion fallback (used by playlist_engine)
SPEED_KEYWORD_MAP = {
    "慢歌": "calm romantic nostalgic",
    "慢": "calm romantic nostalgic",
    "舒缓": "calm romantic",
    "安静": "calm",
    "抒情": "romantic nostalgic",
    "快歌": "energetic party happy",
    "快": "energetic party happy",
    "激情": "energetic",
    "嗨": "party energetic",
    "燃": "energetic",
    "炸": "energetic angry",
    "热血": "energetic",
    "节奏": "energetic party",
    "舞曲": "party energetic",
    "动感": "energetic party",
}
