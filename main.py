"""
Music Agent - 主入口

命令行使用示例:
    # 扫描音乐库
    python main.py scan
    
    # 查询歌曲
    python main.py query "周杰伦的歌"
    
    # 发现新音乐
    python main.py discover
    
    # 生成周报
    python main.py report
    
    # 启动Web界面
    python main.py web
"""
import argparse
import sys
from pathlib import Path
import json

# 修复Windows终端编码
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 加载.env文件
from pathlib import Path as _Path
from dotenv import load_dotenv
_env_path = _Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
else:
    load_dotenv()

from hermes import CLITrigger
from agents import OrganizerAgent, OrganizeStrategy
from agents.librarian import get_librarian


def cmd_scan(args):
    """扫描音乐库"""
    print("🔍 正在扫描音乐库...")
    result = get_librarian().scan_library()

    print(f"\n✅ 扫描完成！")
    print(f"   发现文件: {result['total_files']}")
    print(f"   新增歌曲: {result['new_songs']}")
    print(f"   总计索引: {result['total_indexed']}")


def cmd_query(args):
    """查询歌曲"""
    agent = get_librarian()

    # Hermes Trigger 层：标准化 CLI 输入
    trigger = CLITrigger()
    event = trigger.normalize(args.text)

    print(f"🔍 查询: {event.content}")
    results = agent.query(event.content, top_k=args.top_k)

    if not results:
        print("❌ 没有找到匹配的歌曲")
        return

    print(f"\n🎵 找到 {len(results)} 首相关歌曲:\n")

    for i, item in enumerate(results, 1):
        song = item["song"]
        print(f"{i}. {song.title}")
        print(f"   艺术家: {song.artist}")
        print(f"   专辑: {song.album}")
        print(f"   匹配度: {item['similarity']:.2%}")
        print()


def cmd_web(args):
    """启动Web界面"""
    import subprocess

    web_path = Path(__file__).parent / "web" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(web_path)]

    print("🚀 启动 Web 界面...")
    print(f"   访问 http://localhost:8501\n")

    subprocess.run(cmd)


def cmd_organize(args):
    """整理音乐文件"""
    from graph.utils import load_config

    config = load_config()
    librarian = get_librarian(config)
    organizer = OrganizerAgent(config, librarian)
    
    print("📁 音乐文件整理工具")
    print("=" * 50)
    
    # 如果指定了analyze，只分析当前结构
    if args.analyze:
        print("\n📊 分析当前目录结构...")
        analysis = organizer.run("analyze")
        
        print(f"\n总计: {analysis['total_songs']} 首歌曲")
        print(f"艺术家: {analysis['artists_count']} 位")
        print(f"流派: {analysis['genres_count']} 种")
        
        print("\n🏆 最常听的艺术家:")
        for artist, count in analysis['top_artists'][:5]:
            print(f"   {artist}: {count}首")
        
        print("\n📈 年代分布:")
        for year, count in sorted(analysis['year_distribution'].items()):
            print(f"   {year}: {count}首")
        
        print(f"\n💡 推荐整理策略: {analysis['suggestion']}")
        return
    
    # 确定策略
    strategy = OrganizeStrategy(args.strategy) if args.strategy else None
    
    # 生成计划
    print(f"\n📝 生成整理计划 (策略: {strategy.value if strategy else '默认'})...")
    plan = organizer.run("plan", strategy=strategy)
    
    # 预览
    preview = organizer.preview_plan(plan)
    summary = preview["summary"]
    
    print(f"\n📋 整理预览:")
    print(f"   总文件: {summary['total_files']}")
    print(f"   将移动: {summary['to_move']}")
    print(f"   将复制: {summary['to_copy']}")
    print(f"   跳过(已在正确位置): {summary['skip']}")
    print(f"   冲突(需重命名): {summary['conflicts']}")
    
    if preview["examples"]:
        print(f"\n📝 示例:")
        for ex in preview["examples"][:3]:
            print(f"   {ex['action']}: {Path(ex['from']).name}")
            print(f"      → {Path(ex['to']).name}")
    
    # 询问是否执行
    if not args.yes and not args.dry_run:
        print("\n⚠️  确认执行整理? (y/N): ", end="")
        response = input().strip().lower()
        if response != 'y':
            print("已取消")
            return
    
    # 执行
    print(f"\n{'🔍 模拟执行' if args.dry_run else '🚀 正在整理'}...")
    result = organizer.run("execute", plan=plan, dry_run=args.dry_run)
    
    print(f"\n✅ 完成!")
    print(f"   成功: {result.executed}")
    print(f"   失败: {result.failed}")
    
    if result.failed > 0 and not args.dry_run:
        print("\n❌ 失败的文件:")
        for detail in result.details:
            if detail["status"] == "failed":
                print(f"   {detail['from']}: {detail.get('error', 'Unknown')}")


def main():
    parser = argparse.ArgumentParser(
        description="Music Agent - 智能音乐库管理系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py scan                    # 扫描音乐库
  python main.py query "周杰伦的歌"       # 自然语言查询
  python main.py web                     # 启动Web界面
  python main.py organize --analyze      # 分析当前目录结构
  python main.py organize --strategy artist/album --dry-run  # 预览整理效果
  python main.py organize -y             # 按默认策略整理文件
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # scan 命令
    scan_parser = subparsers.add_parser("scan", help="扫描音乐库")
    
    # query 命令
    query_parser = subparsers.add_parser("query", help="查询歌曲")
    query_parser.add_argument("text", help="查询文本")
    query_parser.add_argument("--top-k", type=int, default=10, help="返回结果数")
    
    # web 命令
    web_parser = subparsers.add_parser("web", help="启动Web界面")
    
    # organize 命令
    organize_parser = subparsers.add_parser("organize", help="整理音乐文件")
    organize_parser.add_argument(
        "--strategy",
        choices=["artist", "album", "genre", "year", "artist/album", "genre/artist", "year/artist"],
        help="整理策略"
    )
    organize_parser.add_argument(
        "--target",
        help="目标目录（覆盖配置）"
    )
    organize_parser.add_argument(
        "--analyze",
        action="store_true",
        help="只分析当前结构，不执行整理"
    )
    organize_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟执行，不实际移动文件"
    )
    organize_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="自动确认，不询问"
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 路由到对应命令
    commands = {
        "scan": cmd_scan,
        "query": cmd_query,
        "web": cmd_web,
        "organize": cmd_organize,
    }
    
    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
