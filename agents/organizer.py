"""
Organizer Agent - 文件分类整理专家

功能：
- 按规则自动整理音乐文件到指定目录结构
- 支持多种分类策略（艺术家/专辑/流派/年代）
- 智能重命名（统一命名格式）
- 预览模式（先看不执行）
- 冲突处理（同名文件检测）
"""
import os
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from .base_agent import BaseAgent
from .librarian import LibrarianAgent, Song


class OrganizeStrategy(Enum):
    """整理策略"""
    BY_ARTIST = "artist"              # 按艺术家
    BY_ALBUM = "album"                # 按专辑
    BY_GENRE = "genre"                # 按流派
    BY_YEAR = "year"                  # 按年代
    BY_ARTIST_ALBUM = "artist/album"  # 艺术家/专辑 二级结构
    BY_GENRE_ARTIST = "genre/artist"  # 流派/艺术家 二级结构
    BY_YEAR_ARTIST = "year/artist"    # 年代/艺术家 二级结构
    FLAT = "flat"                     # 全部平铺到一个文件夹
    RENAME_ONLY = "rename_only"       # 只重命名，不移动
    REMOVE_DUPLICATES = "dedup"       # 检测并标记重复文件
    
    @classmethod
    def from_string(cls, value: str):
        """从字符串获取策略，支持别名"""
        value = value.lower().strip()
        
        # 映射别名
        aliases = {
            "全部": "flat",
            "合并": "flat",
            "平铺": "flat",
            "一个文件夹": "flat",
            "去重": "dedup",
            "重复": "dedup",
            "duplicates": "dedup",
        }
        
        if value in aliases:
            value = aliases[value]
        
        try:
            return cls(value)
        except ValueError:
            return cls.BY_ARTIST_ALBUM  # 默认


@dataclass
class OrganizePlan:
    """整理计划项"""
    song: Song
    source_path: str
    target_path: str
    action: str  # "move" | "rename" | "skip"
    reason: str
    conflict: bool = False


@dataclass
class OrganizeResult:
    """整理结果"""
    total: int
    planned: int
    conflicts: int
    executed: int
    failed: int
    details: List[Dict]


class OrganizerAgent(BaseAgent):
    """
    文件整理Agent
    
    负责将散乱的音乐文件按规则整理到规范目录结构
    """
    
    # 文件名非法字符
    ILLEGAL_CHARS = '<>:"/\\|?*'
    
    def __init__(self, config: Dict[str, Any], librarian: LibrarianAgent = None):
        super().__init__("Organizer", config)
        self.config = config
        self.librarian = librarian
        
        # 目标根目录（如果不设置，使用原目录）
        self.target_root = config.get("organizer", {}).get(
            "target_root", 
            config.get("library", {}).get("path", "./music")
        )
        
        # 默认策略
        self.default_strategy = OrganizeStrategy(
            config.get("organizer", {}).get("default_strategy", "artist/album")
        )
        
        # 文件名模板
        self.filename_template = config.get("organizer", {}).get(
            "filename_template",
            "{artist} - {title}"  # 默认: "周杰伦 - 晴天"
        )
        
        # 是否保留原文件（False则移动，True则复制）
        self.keep_original = config.get("organizer", {}).get("keep_original", False)
        
    def run(self, operation: str = "plan", **kwargs) -> Any:
        """
        执行整理操作
        
        Args:
            operation: plan(生成计划)|preview(预览)|execute(执行)
        """
        if operation == "plan":
            return self.generate_plan(
                strategy=kwargs.get("strategy", self.default_strategy),
                target_root=kwargs.get("target_root", self.target_root)
            )
        
        elif operation == "preview":
            plan = self.generate_plan(
                strategy=kwargs.get("strategy", self.default_strategy),
                target_root=kwargs.get("target_root", self.target_root)
            )
            return self.preview_plan(plan)
        
        elif operation == "execute":
            plan = kwargs.get("plan") or self.generate_plan(
                strategy=kwargs.get("strategy", self.default_strategy),
                target_root=kwargs.get("target_root", self.target_root)
            )
            dry_run = kwargs.get("dry_run", False)
            return self.execute_plan(plan, dry_run=dry_run)
        
        elif operation == "analyze":
            return self.analyze_current_structure()
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    def _find_duplicates(self, show_progress: bool = True) -> Dict[str, List[Song]]:
        """
        查找重复歌曲（基于艺术家+标题）
        
        Args:
            show_progress: 是否显示进度
            
        Returns:
            {歌曲标识: [重复的Song列表]}
        """
        duplicates = {}
        total = len(self.librarian.songs)
        
        for idx, (song_id, song) in enumerate(self.librarian.songs.items(), 1):
            # 使用艺术家+标题作为重复判断键
            key = f"{song.artist.lower()} - {song.title.lower()}"
            
            if key not in duplicates:
                duplicates[key] = []
            duplicates[key].append(song)
            
            # 显示进度
            if show_progress and idx % 50 == 0:
                print(f"\r  扫描进度: {idx}/{total} ({idx*100//total}%)", end="", flush=True)
        
        if show_progress:
            print(f"\r  扫描完成: {total}/{total} (100%)")
        
        # 只返回有重复的
        result = {k: v for k, v in duplicates.items() if len(v) > 1}
        return result
    
    def generate_plan(self, 
                      strategy: OrganizeStrategy = None,
                      target_root: str = None) -> List[OrganizePlan]:
        """
        生成整理计划
        
        Args:
            strategy: 整理策略
            target_root: 目标根目录
        """
        strategy = strategy or self.default_strategy
        target_root = target_root or self.target_root
        
        self.log("info", f"Generating organize plan with strategy: {strategy.value}")
        
        if not self.librarian:
            raise ValueError("LibrarianAgent required")
        
        # 确保音乐库已扫描
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 特殊处理：去重模式
        if strategy == OrganizeStrategy.REMOVE_DUPLICATES:
            return self._generate_dedup_plan(target_root)
        
        plans = []
        target_paths_seen = {}  # 用于检测冲突
        
        for song_id, song in self.librarian.songs.items():
            # 计算目标路径
            target_dir = self._compute_target_directory(song, strategy, target_root)
            target_filename = self._compute_filename(song)
            target_path = os.path.join(target_dir, target_filename)
            
            # 检测冲突
            conflict = False
            if target_path in target_paths_seen:
                conflict = True
                target_path = self._resolve_conflict(target_path, target_paths_seen[target_path])
            
            # 如果路径没有变化，跳过
            if os.path.normpath(song.file_path) == os.path.normpath(target_path):
                action = "skip"
                reason = "Already in correct location"
            else:
                action = "copy" if self.keep_original else "move"
                reason = f"Organize by {strategy.value}"
            
            plan = OrganizePlan(
                song=song,
                source_path=song.file_path,
                target_path=target_path,
                action=action,
                reason=reason,
                conflict=conflict
            )
            
            plans.append(plan)
            target_paths_seen[target_path] = song_id
        
        self.log("info", f"Generated {len(plans)} organize plans")
        return plans
    
    def _generate_dedup_plan(self, target_root: str) -> List[OrganizePlan]:
        """
        生成去重计划（只标记重复，不删除）
        """
        self.log("info", "Generating deduplication plan")
        print("🔍 正在扫描重复歌曲...")
        
        duplicates = self._find_duplicates(show_progress=True)
        
        if not duplicates:
            print("✅ 未发现重复歌曲！")
            return []
        
        print(f"📊 发现 {len(duplicates)} 组重复歌曲")
        print("📝 正在生成去重计划...")
        
        plans = []
        total_dups = sum(len(songs) - 1 for songs in duplicates.values())
        processed = 0
        
        for key, songs in duplicates.items():
            # 保留第一个，标记其他为重复
            sorted_songs = sorted(songs, key=lambda s: (
                0 if " - " in Path(s.file_path).stem else 1,
                -os.path.getsize(s.file_path) if os.path.exists(s.file_path) else 0
            ))
            
            keep_song = sorted_songs[0]
            dup_songs = sorted_songs[1:]
            
            # 保留的歌曲
            plans.append(OrganizePlan(
                song=keep_song,
                source_path=keep_song.file_path,
                target_path=keep_song.file_path,
                action="skip",
                reason=f"保留（最佳版本）- 发现 {len(dup_songs)} 个重复",
                conflict=False
            ))
            
            # 标记重复的歌曲
            for dup in dup_songs:
                dup_dir = os.path.join(target_root, "_duplicates")
                target_path = os.path.join(dup_dir, os.path.basename(dup.file_path))
                
                plans.append(OrganizePlan(
                    song=dup,
                    source_path=dup.file_path,
                    target_path=target_path,
                    action="move",
                    reason=f"重复文件: {key}",
                    conflict=False
                ))
                processed += 1
                if processed % 10 == 0:
                    print(f"\r  处理进度: {processed}/{total_dups}", end="", flush=True)
        
        if total_dups > 0:
            print(f"\r  处理完成: {total_dups}/{total_dups}")
        
        # 添加非重复歌曲（保持原位）
        duplicate_ids = {s.id for songs in duplicates.values() for s in songs}
        for song_id, song in self.librarian.songs.items():
            if song_id not in duplicate_ids:
                plans.append(OrganizePlan(
                    song=song,
                    source_path=song.file_path,
                    target_path=song.file_path,
                    action="skip",
                    reason="非重复文件",
                    conflict=False
                ))
        
        self.log("info", f"Found {len(duplicates)} duplicate groups, {len([p for p in plans if p.action == 'move'])} duplicates to move")
        return plans
    
    def preview_plan(self, plan: List[OrganizePlan]) -> Dict:
        """
        预览整理计划
        
        返回可读的预览信息，不实际执行
        """
        total = len(plan)
        skip = sum(1 for p in plan if p.action == "skip")
        move = sum(1 for p in plan if p.action == "move")
        copy = sum(1 for p in plan if p.action == "copy")
        conflicts = sum(1 for p in plan if p.conflict)
        
        # 按目录分组
        by_directory = {}
        for p in plan:
            if p.action == "skip":
                continue
            dir_path = os.path.dirname(p.target_path)
            if dir_path not in by_directory:
                by_directory[dir_path] = []
            by_directory[dir_path].append({
                "source": p.source_path,
                "filename": os.path.basename(p.target_path),
                "conflict": p.conflict
            })
        
        return {
            "summary": {
                "total_files": total,
                "to_move": move,
                "to_copy": copy,
                "skip": skip,
                "conflicts": conflicts
            },
            "new_structure": {
                dir_path: files
                for dir_path, files in sorted(by_directory.items())
            },
            "examples": [
                {
                    "action": p.action,
                    "from": p.source_path,
                    "to": p.target_path,
                    "reason": p.reason
                }
                for p in plan[:5] if p.action != "skip"
            ]
        }
    
    def execute_plan(self, plan: List[OrganizePlan], dry_run: bool = False) -> OrganizeResult:
        """
        执行整理计划
        
        Args:
            plan: 整理计划
            dry_run: 如果为True，只模拟不实际执行
        """
        self.log("info", f"Executing organize plan (dry_run={dry_run})")
        
        executed = 0
        failed = 0
        details = []
        
        for item in plan:
            if item.action == "skip":
                continue
            
            try:
                if not dry_run:
                    # 确保目标目录存在
                    target_dir = os.path.dirname(item.target_path)
                    os.makedirs(target_dir, exist_ok=True)
                    
                    # 执行移动或复制
                    if item.action == "move":
                        shutil.move(item.source_path, item.target_path)
                    else:  # copy
                        shutil.copy2(item.source_path, item.target_path)
                
                executed += 1
                details.append({
                    "status": "success",
                    "action": item.action,
                    "from": item.source_path,
                    "to": item.target_path
                })
                
            except Exception as e:
                failed += 1
                details.append({
                    "status": "failed",
                    "action": item.action,
                    "from": item.source_path,
                    "to": item.target_path,
                    "error": str(e)
                })
                self.log("error", f"Failed to {item.action} {item.source_path}: {e}")
        
        result = OrganizeResult(
            total=len(plan),
            planned=len([p for p in plan if p.action != "skip"]),
            conflicts=sum(1 for p in plan if p.conflict),
            executed=executed,
            failed=failed,
            details=details
        )
        
        self.log("info", f"Organize complete: {executed} succeeded, {failed} failed")
        return result
    
    def analyze_current_structure(self) -> Dict:
        """
        分析当前目录结构
        """
        if not self.librarian:
            return {}
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 统计艺术家分布
        artists = {}
        genres = {}
        years = {}
        
        for song in self.librarian.songs.values():
            artists[song.artist] = artists.get(song.artist, 0) + 1
            if song.genre:
                genres[song.genre] = genres.get(song.genre, 0) + 1
            if song.year:
                decade = (song.year // 10) * 10
                years[f"{decade}s"] = years.get(f"{decade}s", 0) + 1
        
        return {
            "total_songs": len(self.librarian.songs),
            "artists_count": len(artists),
            "genres_count": len(genres),
            "top_artists": sorted(artists.items(), key=lambda x: x[1], reverse=True)[:10],
            "top_genres": sorted(genres.items(), key=lambda x: x[1], reverse=True)[:10],
            "year_distribution": dict(sorted(years.items())),
            "suggestion": self._suggest_strategy(artists, genres, years)
        }
    
    def _compute_target_directory(self, 
                                   song: Song, 
                                   strategy: OrganizeStrategy,
                                   target_root: str) -> str:
        """
        根据策略计算目标目录
        """
        # 清理非法字符
        def clean(name: str) -> str:
            if not name:
                return "Unknown"
            for char in self.ILLEGAL_CHARS:
                name = name.replace(char, "_")
            return name.strip()
        
        artist = clean(song.artist)
        album = clean(song.album)
        genre = clean(song.genre) if song.genre else "Unknown"
        
        # 计算年代
        if song.year:
            decade = (song.year // 10) * 10
            year_str = f"{decade}s"
        else:
            year_str = "Unknown"
        
        # 根据策略构建路径
        if strategy == OrganizeStrategy.BY_ARTIST:
            return os.path.join(target_root, artist)
        
        elif strategy == OrganizeStrategy.BY_ALBUM:
            return os.path.join(target_root, album)
        
        elif strategy == OrganizeStrategy.BY_GENRE:
            return os.path.join(target_root, genre)
        
        elif strategy == OrganizeStrategy.BY_YEAR:
            return os.path.join(target_root, year_str)
        
        elif strategy == OrganizeStrategy.BY_ARTIST_ALBUM:
            return os.path.join(target_root, artist, album)
        
        elif strategy == OrganizeStrategy.BY_GENRE_ARTIST:
            return os.path.join(target_root, genre, artist)
        
        elif strategy == OrganizeStrategy.BY_YEAR_ARTIST:
            return os.path.join(target_root, year_str, artist)
        
        elif strategy == OrganizeStrategy.FLAT:
            # 全部平铺到目标根目录
            return target_root
        
        elif strategy == OrganizeStrategy.RENAME_ONLY:
            # 保持原目录，只重命名文件
            return os.path.dirname(song.file_path)
        
        elif strategy == OrganizeStrategy.REMOVE_DUPLICATES:
            # 重复检测模式，保持原位置但标记
            return os.path.dirname(song.file_path)
        
        else:
            return target_root
    
    def _compute_filename(self, song: Song) -> str:
        """
        计算目标文件名（支持自定义模板，未知字段自动回退）
        """
        # 获取文件扩展名
        ext = Path(song.file_path).suffix
        
        # 使用模板生成文件名（未知字段安全回退）
        class SafeFormat(dict):
            def __missing__(self, key):
                return "Unknown"
        
        filename = self.filename_template.format_map(SafeFormat(
            artist=song.artist or "Unknown",
            title=song.title or "Unknown",
            album=song.album or "Unknown",
            year=song.year or "Unknown",
            genre=song.genre or "Unknown"
        ))
        
        # 清理非法字符
        for char in self.ILLEGAL_CHARS:
            filename = filename.replace(char, "_")
        
        return filename + ext
    
    def _resolve_conflict(self, target_path: str, existing_id: str) -> str:
        """
        解决文件名冲突
        
        在文件名后添加数字后缀
        """
        base, ext = os.path.splitext(target_path)
        counter = 1
        
        while True:
            new_path = f"{base}_{counter}{ext}"
            if not os.path.exists(new_path):
                return new_path
            counter += 1
            
            # 防止无限循环
            if counter > 1000:
                return f"{base}_{os.urandom(4).hex()}{ext}"
    
    def _suggest_strategy(self, artists: Dict, genres: Dict, years: Dict) -> str:
        """
        根据当前分布推荐整理策略
        """
        # 简单启发式
        if len(artists) > 50:
            return "artist/album"  # 艺术家多，按艺术家/专辑分层
        elif len(genres) > 10:
            return "genre/artist"  # 流派多，按流派/艺术家分层
        elif len(years) > 5:
            return "year/artist"   # 年代分布广，按年代/艺术家分层
        else:
            return "artist"        # 默认按艺术家
