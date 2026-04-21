# -*- coding: utf-8 -*-
"""
Music Agent Chat - 对话式音乐助手（统一版）

启动方式:
    python chat.py

功能:
    • 扫描音乐库 - 建立歌曲索引
    • 智能查询 - "周杰伦的歌"、"适合下雨听的国语歌"
    • 文件整理 - 按艺术家/流派/年代分类
    • 重复检测 - 清理重复歌曲
    • 元数据修复 - 自动补全歌曲信息
    • 发现新音乐 - 从RSS/Reddit发现新歌
    • 模型管理 - 切换Embedding模型
"""
from chat_unified import MusicAgentChat

if __name__ == "__main__":
    chat = MusicAgentChat()
    chat.run()
