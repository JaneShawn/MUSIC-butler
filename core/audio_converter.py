"""
Audio Converter - 音频格式转换工具
支持 WAV 转 FLAC（无损转换）
"""
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass


@dataclass
class ConversionTask:
    """转换任务"""
    source_path: str
    target_path: str
    metadata: Optional[Dict] = None
    status: str = "pending"  # pending, success, failed
    error: str = ""


class AudioConverter:
    """音频转换器"""
    
    SUPPORTED_INPUT = ['.wav', '.aiff', '.aif']
    SUPPORTED_OUTPUT = ['.flac', '.mp3', '.m4a']
    
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
        # 如果没找到，使用已知可用的硬编码路径
        if self.ffmpeg_path is None:
            hardcoded = r"C:\ffmpeg\bin\ffmpeg.exe"
            import os
            if os.path.exists(hardcoded):
                self.ffmpeg_path = hardcoded
        
    def _find_ffmpeg(self) -> Optional[str]:
        """查找 ffmpeg 可执行文件"""
        # 常见路径（优先使用 separate_working.py 中的路径）
        common_paths = [
            r'C:\ffmpeg\bin\ffmpeg.exe',  # 你的环境中可用的路径
            'ffmpeg',
            'ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe',
        ]
        
        for path in common_paths:
            try:
                result = subprocess.run(
                    [path, '-version'],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    print(f"✓ 找到 FFmpeg: {path}")
                    return path
            except:
                continue
        
        return None
    
    def check_ffmpeg(self) -> bool:
        """检查 ffmpeg 是否可用"""
        return self.ffmpeg_path is not None
    
    def get_ffmpeg_install_help(self) -> str:
        """获取 ffmpeg 安装帮助"""
        return """❌ FFmpeg 未安装

FFmpeg 是必需的音频处理工具。

安装方法（Windows）：
1. 下载: https://github.com/BtbN/FFmpeg-Builds/releases
   选择 ffmpeg-master-latest-win64-gpl.zip
2. 解压到 C:\ffmpeg
3. 将 C:\ffmpeg\bin 添加到系统环境变量 PATH
4. 重启终端

或使用包管理器:
   winget install Gyan.FFmpeg

安装后重新运行本程序。"""
    
    def scan_convertible_files(self, directory: str) -> List[str]:
        """扫描可转换的音频文件"""
        files = []
        path = Path(directory)
        
        for ext in self.SUPPORTED_INPUT:
            files.extend(path.rglob(f'*{ext}'))
            files.extend(path.rglob(f'*{ext.upper()}'))
        
        return sorted([str(f) for f in files])
    
    def generate_conversion_plan(self, files: List[str], 
                                  output_format: str = '.flac',
                                  output_dir: Optional[str] = None,
                                  keep_structure: bool = True) -> List[ConversionTask]:
        """
        生成转换计划
        
        Args:
            files: 源文件列表
            output_format: 输出格式
            output_dir: 输出目录（None则使用原目录）
            keep_structure: 是否保持目录结构
        """
        tasks = []
        
        for file_path in files:
            source = Path(file_path)
            
            # 确定输出路径
            if output_dir and keep_structure:
                # 保持相对目录结构
                rel_path = source.relative_to(Path(output_dir).parent if output_dir else source.parent)
                target = Path(output_dir) / rel_path.with_suffix(output_format)
            elif output_dir:
                # 平铺到输出目录
                target = Path(output_dir) / source.with_suffix(output_format).name
            else:
                # 同目录，改后缀
                target = source.with_suffix(output_format)
            
            tasks.append(ConversionTask(
                source_path=str(source),
                target_path=str(target)
            ))
        
        return tasks
    
    def convert_file(self, task: ConversionTask, 
                     progress_callback: Optional[Callable] = None) -> bool:
        """
        转换单个文件
        
        Args:
            task: 转换任务
            progress_callback: 进度回调函数(percent, message)
        
        Returns:
            是否成功
        """
        if not self.ffmpeg_path:
            task.status = "failed"
            task.error = "FFmpeg 未安装"
            return False
        
        source = Path(task.source_path)
        target = Path(task.target_path)
        
        # 确保目标目录存在
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # 构建 ffmpeg 命令
        cmd = [
            self.ffmpeg_path,
            '-i', str(source),           # 输入文件
            '-y',                         # 覆盖输出文件
            '-map_metadata', '0',         # 保留元数据
            '-c:a', 'flac',               # 使用 FLAC 编码
            '-compression_level', '5',    # 压缩级别（0-12，5是平衡）
            str(target)
        ]
        
        try:
            if progress_callback:
                progress_callback(10, f"正在转换: {source.name}")
            
            # 执行转换
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode == 0:
                task.status = "success"
                if progress_callback:
                    progress_callback(100, f"完成: {target.name}")
                return True
            else:
                task.status = "failed"
                task.error = result.stderr[:200] if result.stderr else "转换失败"
                return False
                
        except subprocess.TimeoutExpired:
            task.status = "failed"
            task.error = "转换超时"
            return False
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            return False
    
    def batch_convert(self, tasks: List[ConversionTask],
                      progress_callback: Optional[Callable] = None) -> Dict:
        """
        批量转换
        
        Returns:
            {
                'total': 总数,
                'success': 成功数,
                'failed': 失败数,
                'tasks': 任务列表
            }
        """
        total = len(tasks)
        success = 0
        failed = 0
        
        for i, task in enumerate(tasks):
            if progress_callback:
                overall = int((i / total) * 100)
                progress_callback(overall, f"[{i+1}/{total}] {Path(task.source_path).name}")
            
            if self.convert_file(task, progress_callback):
                success += 1
            else:
                failed += 1
        
        return {
            'total': total,
            'success': success,
            'failed': failed,
            'tasks': tasks
        }
    
    def delete_source_files(self, tasks: List[ConversionTask],
                            dry_run: bool = True) -> Dict:
        """
        删除源文件（转换成功后）
        
        Args:
            tasks: 转换任务列表
            dry_run: 是否仅预览
        
        Returns:
            {'deleted': 删除数, 'errors': 错误数, 'details': 详情}
        """
        deleted = 0
        errors = 0
        details = []
        
        for task in tasks:
            if task.status != "success":
                continue
            
            try:
                if not dry_run:
                    Path(task.source_path).unlink()
                deleted += 1
                details.append({
                    'file': task.source_path,
                    'status': 'deleted' if not dry_run else 'would_delete'
                })
            except Exception as e:
                errors += 1
                details.append({
                    'file': task.source_path,
                    'status': 'error',
                    'error': str(e)
                })
        
        return {
            'deleted': deleted,
            'errors': errors,
            'details': details,
            'dry_run': dry_run
        }


def preview_conversion(library_path: str) -> Dict:
    """
    预览可转换的文件
    
    Returns:
        {
            'convertible': [{'source': '...', 'target': '...'}, ...],
            'total_size_mb': 总大小,
            'estimated_savings_mb': 预计节省空间
        }
    """
    converter = AudioConverter()
    files = converter.scan_convertible_files(library_path)
    
    if not files:
        return {'convertible': [], 'total_size_mb': 0, 'estimated_savings_mb': 0}
    
    # 生成转换计划
    tasks = converter.generate_conversion_plan(files)
    
    # 计算大小
    total_size = sum(Path(t.source_path).stat().st_size for t in tasks)
    
    # FLAC 通常比 WAV 节省 30-50% 空间
    estimated_target_size = total_size * 0.6
    savings = total_size - estimated_target_size
    
    return {
        'convertible': [
            {
                'source': t.source_path,
                'target': t.target_path,
                'size_mb': round(Path(t.source_path).stat().st_size / 1024 / 1024, 2)
            }
            for t in tasks
        ],
        'total_size_mb': round(total_size / 1024 / 1024, 2),
        'estimated_savings_mb': round(savings / 1024 / 1024, 2),
        'task_count': len(tasks)
    }
