# -*- coding: utf-8 -*-
"""InfoHandlers - handler mixin for MusicAgentChat."""
from typing import Dict, Any
class InfoHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_info(self, params: Dict) -> str:
        item = params.get("item", {})
        song = item.get('song', item)
        return f"""📀 {song.title}
👤 艺术家: {song.artist}
💿 专辑: {song.album or '未知'}
🎵 流派: {song.genre or '未知'}
📅 年份: {song.year or '未知'}
📁 文件: {song.file_path}"""
    

    def handle_cancel(self, params: Dict) -> str:
        if self.context.pending_action:
            desc = self.context.pending_action.description
            self.context.clear_pending()
            return f"已取消: {desc}"
        return "没有待执行的操作。"
    

    def handle_clear(self, params: Dict) -> str:
        count = len(self.context.messages)
        self.context.clear()
        return f"会话已重置（清除了 {count} 条消息）。"
    

    def handle_chat(self, params: Dict) -> str:
        chat_type = params.get("type", "general")
        content = params.get("content", "")
        
        if self.kimi:
            try:
                return self._generate_response(chat_type, content)
            except:
                pass
        return self._preset_response(chat_type, content)
    
    def _generate_response(self, chat_type: str, content: str) -> str:
        """使用Kimi生成回复"""
        system = """你是友好幽默的音乐助手Music Agent。特点：
1. 热爱音乐，了解各种风格
2. 像朋友一样轻松聊天
3. 回答简短自然，30-80字
4. 记住对话上下文，保持连贯
5. ⚠️ 重要：你不知道用户的音乐库里有什么歌，也绝不能编造任何具体数字（如"你有375首英语歌"）。如果用户询问具体统计，请引导用户使用正确的命令。"""
        
        context = self.context.get_context_text(4)
        pending = f"\n[待确认操作: {self.context.pending_action.description}]" if self.context.pending_action else ""
        
        prompt = f"""对话上下文：
{context}{pending}

用户说：{content}

请自然友好地回复（简短）："""
        
        return self.kimi.generate(prompt, system=system, temperature=0.8, max_tokens=150) or self._preset_response(chat_type, content)
    
    def _preset_response(self, chat_type: str, content: str) -> str:
        import random
        
        if chat_type == "greeting":
            return random.choice([
                "你好！今天想听什么歌？",
                "嗨！需要我帮你整理音乐库吗？",
                "欢迎！今天音乐心情如何？"
            ])
        elif chat_type == "emotion":
            if any(w in content for w in ["无聊", "烦"]):
                return "来首歌提提神？要我推荐一些节奏感强的歌吗？"
            elif any(w in content for w in ["难过", "郁闷"]):
                return "抱抱~ 听点舒缓的音乐可能会好一些。"
            elif any(w in content for w in ["开心", "高兴"]):
                return "太好了！开心的时候最适合听歌了！"
            elif "累" in content:
                return "辛苦了！来点轻音乐放松一下？"
            return "音乐是最好的情绪调节剂~"
        else:
            return random.choice([
                "有趣的话题！你的音乐库需要整理一下吗？",
                "最近有听什么好歌吗？",
                "需要我帮你扫描一下音乐库吗？"
            ])
    

    def handle_help(self, params: Dict) -> str:
        return """Music Agent Chat - 功能列表

【基本操作】
• "扫描" - 扫描音乐库，建立索引
• "分析" - 统计歌曲、艺术家、流派分布
• "帮助" - 显示此帮助
• "清除会话" - 重置对话历史

【文件整理】
• "整理音乐" - 按艺术家/专辑分类（预览→确认）
• "平铺所有歌曲" - 合并到一个文件夹
• "按流派整理" - 按音乐风格分类
• "按年代整理" - 按年份分类
• "清理重复" - 检测并移动重复文件

【智能查询】
• "周杰伦的歌" - 搜索特定歌手
• "推荐适合下雨听的" - 按场景/情绪
• "有哪些粤语歌" - 按语言筛选
• 查询后可输入: 1 | 第一首 | 播放第一首

【元数据修复】
• "修复元数据" - 批量修复所有歌曲
• "修复元数据并下载封面" - 批量修复+封面
• "修复这首歌" - 修复查询结果中的歌曲
• "重新识别" / "强制修复" - 强制重新识别（无视现有标签）
• "确认修复" - 执行修复操作
💡 建议：如果现有标签错误，用"重新识别"强制更新

【格式转换】
• "转换 wav 到 flac" - 批量转换格式
• "转换并删除源文件" - 转换后删除 WAV
• "删除 wav" - 直接删除所有 WAV 文件（⚠️ 不转换）
• "确认转换" / "确认删除" - 执行操作
💡 WAV→FLAC 可节省 30-50% 空间，同时支持元数据标签

【发现新音乐】
• "发现新音乐" / "生成周报" - 自动发现本周新歌并评估是否适合你
• "给我推荐" / "推荐歌曲" - 基于你的音乐库偏好推荐
• "发现像陈奕迅的歌" - 找相似风格的歌曲
• "工作时的歌" / "学习音乐" / "运动歌单" - 按场景发现
• "小众音乐" / "冷门独立" - 探索不为人知的好歌
• "周杰伦 新专辑" - 追踪特定艺术家的最新发行

【播放列表】
• "创建一个播放列表" - 随机生成（foobar2000格式）
• "创建一个30分钟的播放列表" - 指定时长
• "创建一个适合工作的50首歌单" - 智能生成
• "随机播放列表" - 完全随机打乱
• 播放列表保存到 /Playlists 目录，支持 foobar2000

【情绪播放列表】🎭
• "创建一个快乐的播放列表" / "开心歌单" - 快乐正能量
• "创建一个悲伤的播放列表" / "治愈歌单" - 安静治愈
• "创建一个激情的播放列表" / "燃向歌单" - 热血高能
• "创建一个平静的播放列表" / "放松歌单" - 舒缓放松
• "创建一个浪漫的播放列表" - 甜蜜情歌
• "创建一个怀旧的播放列表" - 经典金曲
• "创建一个专注的播放列表" - 工作学习背景音
• "创建一个派对的播放列表" - 嗨翻全场
• "分析情绪" / "分析歌词" / "分析歌曲" - 分析音乐库情绪分布（自动获取歌词）
• "生成歌词" / "下载歌词文件" - 从网易云批量下载歌词
• "识别XX歌词" / "提取XX歌词" / "AI识别" - 使用Whisper识别任意歌曲歌词（需安装）
• "哪些是比较浪漫的" / "推荐悲伤的歌" - 查询本地库中该情绪的歌曲

【模型管理】
• "当前模型" - 查看使用的Embedding模型
• "列出模型" - 显示所有可用模型
• "切换模型 bge-large-zh" - 更换语义模型

【退出】输入: 退出 | 再见 | bye"""
    

