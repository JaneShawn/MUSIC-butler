# -*- coding: utf-8 -*-
"""DiscoverHandlers - handler mixin for MusicAgentChat."""
import os
from typing import Dict, Any, List
from pathlib import Path
class DiscoverHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_discover(self, params: Dict) -> str:
        """发现新音乐 - 支持多种模式"""
        mode = params.get("mode", "default")
        
        # 主动发现模式
        if mode != "default":
            from agents.scout import DiscoveryRequest
            
            if mode == "similar_artist":
                artist = params.get("artist", "")
                if not artist:
                    return "请指定艺术家，例如：'发现像陈奕迅的歌'"
                print(f"🔍 正在发现与 {artist} 风格相似的歌曲...")
                request = DiscoveryRequest("similar_artist", {"artist": artist, "top_k": 8}, f"与{artist}相似的歌曲")
                
            elif mode == "mood":
                mood = params.get("mood", "relax")
                mood_names = {"work": "工作", "study": "学习", "workout": "运动", 
                             "relax": "放松", "sleep": "睡眠", "party": "派对", "commute": "通勤"}
                print(f"🎵 正在发现适合{mood_names.get(mood, mood)}时听的歌...")
                request = DiscoveryRequest("mood", {"mood": mood}, f"适合{mood}场景")
                
            elif mode == "artist_new":
                artist = params.get("artist", "")
                if not artist:
                    return "请指定艺术家，例如：'陈奕迅 新专辑'"
                print(f"🆕 正在发现 {artist} 的最新发行...")
                request = DiscoveryRequest("artist_new", {"artist": artist}, f"{artist}的最新歌曲")
                
            elif mode == "explore":
                print("🌟 正在探索小众独立音乐...")
                request = DiscoveryRequest("explore", {}, "小众/冷门音乐")
            
            elif mode == "based_on_library":
                print("📚 正在分析你的音乐库偏好...")
                # 获取用户库中的 top 艺术家
                if not self.librarian.songs:
                    self.librarian.run("scan")
                
                stats = self.librarian.get_stats()
                top_artists = [a[0] for a in stats.get("top_artists", [])[:5]]
                
                if not top_artists:
                    return "你的音乐库还没有足够的歌曲来进行推荐。先添加一些歌曲吧！"
                
                print(f"   根据你喜欢的: {', '.join(top_artists[:3])}")
                request = DiscoveryRequest(
                    "based_on_library", 
                    {"librarian": self.librarian, "top_artists": top_artists},
                    f"基于你的音乐库（Top艺术家: {', '.join(top_artists[:3])}）"
                )
            else:
                return f"未知的发现模式: {mode}"
            
            try:
                candidates = self.scout.run("active", discovery_request=request)
                
                if not candidates:
                    return f"暂时没有符合条件的歌曲，换个条件试试吧！"
                
                print(f"📬 发现 {len(candidates)} 首候选歌曲")
                
                # 主动发现模式不经过策展人评估（因为是你主动要求的）
                rec_lines = []
                for i, song in enumerate(candidates[:8], 1):
                    reason = song.metadata.get("reason", "")
                    rec_lines.append(f"{i}. 《{song.title}》- {song.artist}")
                    if reason:
                        rec_lines.append(f"   💡 {reason}")
                
                return f"""🎵 {request.reason}

发现 {len(candidates)} 首歌曲：
{chr(10).join(rec_lines)}

💡 提示: 可以对我说"播放第3首"来播放"""
                
            except Exception as e:
                return f"发现音乐时出错了: {e}"
        
        # 默认模式：自动发现新发行
        print("🔍 正在发现新音乐...")
        
        try:
            candidates = self.scout.run("all")
            if not candidates:
                return "本周没有发现新音乐，下周再来看看吧！"
            
            print(f"📬 发现 {len(candidates)} 首候选歌曲")
            print("🤖 策展人正在评估...")
            
            recommendations = self.curator.run("evaluate", candidates=candidates)
            
            if not recommendations:
                return "本周没有发现适合你的新音乐，下次再看看！"
            
            # 生成报告
            report = self.curator.run("report", recommendations=recommendations)
            
            # 格式化输出
            rec_lines = []
            for i, rec in enumerate(report['recommendations'][:5], 1):
                badge = "⭐" if rec.get('action') == 'highly_recommend' else "👍"
                rec_lines.append(f"{badge} 《{rec['title']}》- {rec['artist']}")
                rec_lines.append(f"   推荐理由: {rec['reason']}")
            
            return f"""📊 {report['title']}

本周发现: {report['summary']['total_discovered']} 首
强烈推荐: {report['summary']['highly_recommended']} 首
涉及流派: {', '.join(report['summary']['genres'])}

本周推荐:
{chr(10).join(rec_lines)}

💡 更多发现方式：
• "发现像陈奕迅的歌" - 找相似风格
• "工作时的歌" - 按场景发现  
• "小众音乐" - 探索冷门佳作
• "周杰伦 新专辑" - 追踪新发行"""
            
        except Exception as e:
            return f"发现新音乐时出错了: {e}\n可能需要配置 Reddit API 或检查网络连接。"
    

    def handle_recommend_random(self, params: Dict) -> str:
        """随机推荐歌曲并说明理由"""
        import random
        
        count = params.get("count", 5)
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not self.librarian.songs:
            return "音乐库为空"
        
        # 随机选择歌曲
        all_songs = list(self.librarian.songs.values())
        selected = random.sample(all_songs, min(count, len(all_songs)))
        
        print(f"🎲 随机选择了 {len(selected)} 首歌曲，正在生成推荐理由...")
        
        # 保存到上下文，支持"播放第X首"
        self.context.last_query_results = [{"song": s} for s in selected]
        
        # 使用LLM生成推荐理由
        recommendations = []
        for i, song in enumerate(selected, 1):
            reason = self._generate_recommendation_reason(song)
            recommendations.append(f"{i}. 《{song.title}》- {song.artist}\n   💡 {reason}")
        
        return f"""
🎯 为你随机推荐 {len(selected)} 首歌：

{chr(10).join(recommendations)}

💿 输入"播放第X首"或"1/2/3"直接播放，"播放全部"生成歌单
"""
    
    def _generate_recommendation_reason(self, song) -> str:
        """生成歌曲推荐理由"""
        # 尝试获取情绪信息
        emotion_desc = ""
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
            analyzer = SimpleEmotionAnalyzer()
            cache_key = analyzer._get_file_hash(song.file_path)
            if cache_key in analyzer._cache:
                emotion = analyzer._cache[cache_key].get('emotion', '')
                emotion_names = {
                    'happy': '充满活力', 'sad': '深情动人', 'energetic': '热血沸腾',
                    'calm': '宁静治愈', 'romantic': '浪漫甜蜜', 'nostalgic': '怀旧经典',
                    'angry': '情绪宣泄', 'focus': '专注沉浸', 'party': '欢快派对'
                }
                emotion_desc = emotion_names.get(emotion, '')
        except:
            pass
        
        # 基于元数据生成理由
        reasons = []
        
        if emotion_desc:
            reasons.append(f"{emotion_desc}的风格")
        
        if song.genre:
            reasons.append(f"经典的{song.genre}")
        
        if song.year:
            current_year = 2024
            if current_year - int(song.year) > 20:
                reasons.append(f"{song.year}年的怀旧之作")
            elif current_year - int(song.year) < 5:
                reasons.append(f"近年新发行")
        
        if song.artist:
            reasons.append(f"{song.artist}的代表作品")
        
        # 保底理由
        if not reasons:
            reasons = ["独特的音乐魅力", "值得细细品味"]
        
        # 如果有LLM，用LLM生成更好的理由
        if self.kimi and len(reasons) > 0:
            try:
                prompt = f"""歌曲：《{song.title}》- {song.artist}
风格：{song.genre or '未知'}
情绪：{emotion_desc or '未知'}

用1句话（20字以内）推荐这首歌，要文艺、有感染力："""
                
                response = self.kimi.chat([{"role": "user", "content": prompt}])
                if response and len(response) < 50:
                    return response.strip('"')
            except:
                pass
        
        return "，".join(reasons[:2])
    
    def _create_m3u8_playlist(self, songs: List, playlist_name: str) -> Path:
        """创建 M3U8 播放列表文件
        
        关键：M3U8 中的路径必须是相对于 M3U8 文件所在目录的，
        这样 foobar2000 才能正确解析。
        """
        from pathlib import Path
        playlist_dir = Path(self.config.get("library", {}).get("path", ".")) / "Playlists"
        playlist_dir.mkdir(exist_ok=True)
        
        playlist_path = playlist_dir / f"{playlist_name}.m3u8"
        
        import os
        lines = ["#EXTM3U", f"#PLAYLIST:{playlist_name}"]
        for song in songs:
            # 路径必须是相对于 M3U8 文件所在目录的（不是相对于 library_path）
            # 用 os.path.relpath 处理兄弟目录关系（如 Playlists/../MUSIC/xxx）
            try:
                rel_path = os.path.relpath(song.file_path, playlist_dir)
                # Windows 反斜杠转为正斜杠（M3U8 标准用正斜杠）
                rel_path = rel_path.replace(os.sep, '/')
            except ValueError:
                # 不同盘符，只能用绝对路径
                rel_path = song.file_path
            
            duration = getattr(song, 'duration', 240) or 240
            lines.append(f"#EXTINF:{int(duration)},{song.artist} - {song.title}")
            lines.append(rel_path)
        
        playlist_path.write_text("\n".join(lines), encoding='utf-8')
        return playlist_path
    

