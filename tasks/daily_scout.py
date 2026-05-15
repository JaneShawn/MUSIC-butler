"""
定时任务 - 每日音乐发现

使用方法:
    python tasks/daily_scout.py

或使用APScheduler:
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(daily_scout_job, 'cron', hour=9)
"""
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import json
from datetime import datetime

from agents import LibrarianAgent, ScoutAgent, CuratorAgent


def load_config():
    """加载配置"""
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def daily_scout_job():
    """每日发现任务"""
    print(f"[{datetime.now()}] 开始每日音乐发现任务...")
    
    config = load_config()
    
    # 初始化Agent
    from agents.librarian import get_librarian
    librarian = get_librarian(config)
    scout = ScoutAgent(config)
    curator = CuratorAgent(config, librarian)
    
    # 1. 同步本地库
    print("同步本地音乐库...")
    librarian.run("scan")
    
    # 2. 发现新音乐
    print("搜索新音乐...")
    candidates = scout.run("all")
    
    if not candidates:
        print("未发现新音乐")
        return
    
    print(f"发现 {len(candidates)} 首候选歌曲")
    
    # 3. 评估推荐
    recommendations = curator.run("evaluate", candidates=candidates)
    
    if not recommendations:
        print("没有符合偏好的推荐")
        return
    
    print(f"生成 {len(recommendations)} 条推荐")
    
    # 4. 保存结果
    report = curator.run("report", recommendations=recommendations)
    
    # 保存到文件
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / f"report_{datetime.now().strftime('%Y%m%d')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"报告已保存: {output_file}")
    
    # 5. 打印摘要
    print("\n=== 今日发现摘要 ===")
    for rec in recommendations[:5]:
        badge = "⭐" if rec.action == "highly_recommend" else "👍"
        print(f"{badge} {rec.candidate.artist} - {rec.candidate.title}")


if __name__ == "__main__":
    daily_scout_job()
