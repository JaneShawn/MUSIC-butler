"""
Lyrics Generator - 使用AI识别/生成歌词
支持：Whisper语音识别、Kimi听写
"""
import os
from pathlib import Path
from typing import Optional, Dict
import tempfile


class LyricsGenerator:
    """
    歌词生成器
    
    方法1: Whisper本地识别（推荐，准确率高）
    方法2: Kimi API听写（无需安装，但消耗token）
    """
    
    def __init__(self, kimi_client=None):
        self.kimi = kimi_client
        self.whisper_available = self._check_whisper()
    
    def _check_whisper(self) -> bool:
        """检查是否安装了whisper"""
        try:
            import whisper
            return True
        except ImportError:
            return False
    
    def generate(self, audio_file: str, method: str = "auto") -> Optional[str]:
        """
        生成/识别歌词
        
        Args:
            audio_file: 音频文件路径
            method: "whisper" | "kimi" | "auto"
        
        Returns:
            识别出的歌词文本，或None
        """
        if method == "auto":
            if self.whisper_available:
                method = "whisper"
            elif self.kimi:
                method = "kimi"
            else:
                return None
        
        if method == "whisper":
            return self._generate_with_whisper(audio_file)
        elif method == "kimi":
            return self._generate_with_kimi(audio_file)
        else:
            return None
    
    def _generate_with_whisper(self, audio_file: str) -> Optional[str]:
        """使用OpenAI Whisper本地识别，返回LRC格式歌词"""
        if not self.whisper_available:
            print("[WARN] Whisper未安装，尝试安装: pip install openai-whisper")
            return None
        
        try:
            import whisper
            
            # 尝试检查GPU是否可用
            device = "cpu"
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    gpu_name = torch.cuda.get_device_name(0)
                    print(f"  ✅ 使用GPU加速: {gpu_name}")
                else:
                    print(f"  ⚠️  PyTorch未检测到GPU，使用CPU运行")
            except ImportError:
                print(f"  ℹ️  未安装PyTorch，使用CPU运行")
            except Exception as e:
                print(f"  ⚠️  GPU检测失败: {e}，使用CPU运行")
            
            print(f"  识别: {Path(audio_file).name}")
            print(f"  加载 large 模型（首次使用需下载约1.5GB）...")
            
            # 加载模型（large模型最准确，但较慢）
            model = whisper.load_model("large", device=device)
            
            # 识别（自动检测语言，不强制中文）
            result = model.transcribe(
                audio_file,
                language=None,  # 自动检测语言
                task="transcribe",
                verbose=False,
                condition_on_previous_text=True,  # 保持上下文连贯
                initial_prompt="This is a song lyrics."  # 提示模型这是歌词
            )
            
            # 生成标准LRC格式（带时间戳，过滤垃圾内容）
            segments = result.get("segments", [])
            if not segments:
                return None
            
            # 垃圾内容过滤词
            noise_words = [
                "作曲", "作词", "编曲", "制作人", "监制", "混音",
                "音乐", "曲", "词", "编", "制作", "监制",
                "优优独播剧场", "YoYo Television", "独家", "首播",
                "片头", "片尾", "插曲", "主题曲", "片尾曲",
                "字幕", "制作", "出品", "发行", "版权",
                "敬請", "請", "收聽", "收听", "观看"
            ]
            
            def is_noise(text: str) -> bool:
                """检查是否为垃圾内容"""
                text = text.strip()
                # 太短的不是歌词
                if len(text) < 3:
                    return True
                # 包含过滤词
                for noise in noise_words:
                    if noise in text:
                        return True
                # 纯标点或数字
                if text.replace(".", "").replace("-", "").isdigit():
                    return True
                # 乱码检测（包含大量非中英文字符）
                normal_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or c.isalpha() or c.isdigit() or c in " .,!?-'")
                if normal_chars < len(text) * 0.5:
                    return True
                return False
            
            lrc_lines = []
            prev_text = ""  # 用于去重
            
            for seg in segments:
                start_time = seg.get("start", 0)
                text = seg.get("text", "").strip()
                
                # 跳过垃圾内容
                if not text or is_noise(text):
                    continue
                
                # 跳过重复行（有些歌会重复识别）
                if text == prev_text:
                    continue
                prev_text = text
                
                # 转换为 [mm:ss.xx] 格式
                minutes = int(start_time // 60)
                seconds = int(start_time % 60)
                hundredths = int((start_time - int(start_time)) * 100)
                timestamp = f"[{minutes:02d}:{seconds:02d}.{hundredths:02d}]"
                lrc_lines.append(f"{timestamp}{text}")
            
            # 添加LRC文件头
            lrc_content = "[ti:]\n[ar:]\n[al:]\n\n" + "\n".join(lrc_lines)
            
            if len(lrc_lines) > 3:  # 至少3行有效歌词
                return lrc_content
            else:
                return None
                
        except Exception as e:
            print(f"[ERROR] Whisper识别失败: {e}")
            return None
    
    def _generate_with_kimi(self, audio_file: str) -> Optional[str]:
        """使用Kimi API听写（需要音频上传功能）"""
        if not self.kimi:
            return None
        
        try:
            # 注意：Kimi目前不支持直接上传音频文件
            # 这里提供一个替代方案：提取音频片段转base64
            print(f"  Kimi暂不支持直接音频识别，建议安装Whisper")
            return None
            
        except Exception as e:
            print(f"[ERROR] Kimi识别失败: {e}")
            return None
    
    def batch_generate(self, songs: list, progress_callback=None) -> Dict[str, str]:
        """批量生成歌词"""
        results = {}
        
        for i, song in enumerate(songs):
            file_path = song.get('file_path')
            title = song.get('title', 'Unknown')
            
            print(f"\n[{i+1}/{len(songs)}] 识别: {title}")
            
            lyrics = self.generate(file_path)
            if lyrics:
                results[file_path] = lyrics
                print(f"  ✓ 识别成功 ({len(lyrics)} 字符)")
            else:
                print(f"  ✗ 识别失败")
            
            if progress_callback:
                progress_callback(i + 1, len(songs))
        
        return results
    
    def save_lyrics(self, audio_file: str, lyrics: str, output_dir: str = "data/lyrics") -> bool:
        """保存LRC格式歌词到文件"""
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # 使用"艺术家 - 标题.lrc"作为文件名
            from core.lyrics_fetcher import LyricsFetcher
            fetcher = LyricsFetcher(lyrics_dir=output_dir)
            
            # 从音频文件路径获取歌曲信息
            base_name = Path(audio_file).stem
            # 尝试解析 "艺术家 - 标题" 格式
            if " - " in base_name:
                parts = base_name.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
                safe_name = fetcher._safe_filename(f"{artist} - {title}")
            else:
                safe_name = fetcher._safe_filename(base_name)
            
            lrc_file = output_path / f"{safe_name}.lrc"
            
            # 直接保存LRC内容（已经是标准格式）
            lrc_content = lyrics if lyrics.strip().startswith('[') else f"[00:00.00]{lyrics}"
            lrc_file.write_text(lrc_content, encoding='utf-8')
            
            return True
        except Exception as e:
            print(f"[ERROR] 保存歌词失败: {e}")
            return False


def install_whisper_hint():
    """显示Whisper安装提示"""
    print("""
要使用AI识别歌词功能，需要安装OpenAI Whisper:

安装命令:
    pip install openai-whisper

如果需要GPU加速（需CUDA）:
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    pip install openai-whisper

检查GPU是否可用:
    python -c "import torch; print('GPU可用:', torch.cuda.is_available())"

注意:
    - 首次使用会自动下载模型(large约1.5GB)
    - 需要ffmpeg支持音频解码
    - 有NVIDIA GPU会快5-10倍，CPU也能运行但较慢
""")
