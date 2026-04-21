"""
Embedding模型管理工具
- 预下载模型
- 清理/重建向量数据库
- 测试模型效果
"""
import argparse
import shutil
from pathlib import Path
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.vector_store import EMBEDDING_MODELS, get_embedding_function, _check_sentence_transformers


def check_dependency():
    """检查依赖是否安装"""
    if not _check_sentence_transformers():
        print("""
❌ sentence-transformers 未安装

这个工具需要 sentence-transformers 才能运行。

安装命令：
   pip install sentence-transformers

如果安装失败（如Windows长路径问题），可以：
1. 先使用ChromaDB默认embedding（无需安装）
2. 运行 chat.py 正常使用查询功能
3. 有空时再尝试安装 sentence-transformers 以获得更好的中文检索效果

当前状态：ChromaDB默认embedding可用，查询功能正常
""")
        return False
    return True


def list_models():
    """列出所有可用的embedding模型"""
    if not check_dependency():
        return
    print("\n📋 可用Embedding模型：\n")
    print(f"{'别名':<20} {'模型名称':<50} {'描述'}")
    print("-" * 90)
    
    descriptions = {
        "bge-small-zh": "中文轻量模型，速度快，适合大多数场景",
        "bge-large-zh": "中文高精度模型，质量更好但较慢",
        "bge-base-zh": "中文平衡模型，速度和质量折中",
        "paraphrase-multilingual": "多语言模型，支持50+语言",
        "all-MiniLM": "英文轻量模型（不推荐中文）",
    }
    
    for alias, model_name in EMBEDDING_MODELS.items():
        desc = descriptions.get(alias, "")
        print(f"{alias:<20} {model_name:<50} {desc}")
    print()


def download_model(model_alias: str):
    """预下载embedding模型"""
    if not check_dependency():
        return
    if model_alias not in EMBEDDING_MODELS:
        print(f"❌ 未知模型: {model_alias}")
        print(f"可用模型: {', '.join(EMBEDDING_MODELS.keys())}")
        return
    
    model_name = EMBEDDING_MODELS[model_alias]
    print(f"📥 正在下载/加载模型: {model_name}")
    print("⏳ 首次下载需要几分钟，请耐心等待...\n")
    
    try:
        # 触发模型下载
        ef = get_embedding_function(model_name)
        
        # 测试编码
        test_texts = [
            "周杰伦 - 晴天",
            "摇滚音乐",
            "适合下雨听的安静歌曲"
        ]
        embeddings = ef(test_texts)
        
        print(f"✅ 模型加载成功！")
        print(f"   测试文本数: {len(test_texts)}")
        print(f"   向量维度: {len(embeddings[0])}")
        print(f"   模型已缓存到本地，下次使用无需下载\n")
        
    except Exception as e:
        print(f"❌ 模型下载失败: {e}\n")


def reset_vector_db():
    """清理向量数据库（更换模型后必须执行）"""
    chroma_dir = Path("./data/chroma")
    
    if not chroma_dir.exists():
        print("ℹ️ 向量数据库目录不存在，无需清理\n")
        return
    
    print("⚠️  警告: 这将删除所有已索引的歌曲向量！")
    print(f"   目录: {chroma_dir.absolute()}")
    response = input("   确认删除? (yes/no): ").strip().lower()
    
    if response == "yes":
        try:
            shutil.rmtree(chroma_dir)
            print("✅ 向量数据库已清理\n")
            print("💡 下次运行 scan 命令时会自动重建索引\n")
        except Exception as e:
            print(f"❌ 清理失败: {e}\n")
    else:
        print("已取消\n")


def test_query(model_alias: str):
    """测试模型效果"""
    if not check_dependency():
        return
    print(f"\n🧪 测试模型: {model_alias}\n")
    
    # 加载模型
    try:
        ef = get_embedding_function(model_alias)
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        return
    
    # 模拟歌曲数据
    songs = [
        "Song: 晴天 | Artist: 周杰伦 | Album: 叶惠美 | Genre: 流行",
        "Song: 七里香 | Artist: 周杰伦 | Album: 七里香 | Genre: 流行",
        "Song: 挪威的森林 | Artist: 伍佰 | Album: 爱情的尽头 | Genre: 摇滚",
        "Song: Last Dance | Artist: 伍佰 | Album: 爱情的尽头 | Genre: 摇滚",
        "Song: Bohemian Rhapsody | Artist: Queen | Album: A Night at the Opera | Genre: Rock",
        "Song: Hotel California | Artist: Eagles | Album: Hotel California | Genre: Rock",
    ]
    
    # 生成embedding
    print("📊 生成歌曲向量...")
    song_embeddings = ef(songs)
    
    # 测试查询
    test_queries = [
        "周杰伦的歌",
        "摇滚音乐",
        "伍佰的经典歌曲",
        "英文摇滚",
    ]
    
    import numpy as np
    
    for query in test_queries:
        print(f"\n🔍 查询: \"{query}\"")
        query_embedding = ef([query])[0]
        
        # 计算相似度
        similarities = []
        for i, song_emb in enumerate(song_embeddings):
            # 余弦相似度
            sim = np.dot(query_embedding, song_emb) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(song_emb)
            )
            similarities.append((songs[i], sim))
        
        # 排序并显示Top 3
        similarities.sort(key=lambda x: x[1], reverse=True)
        for song, sim in similarities[:3]:
            marker = "✓" if sim > 0.5 else " "
            print(f"   [{marker}] {sim:.3f} | {song[:50]}...")
    
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Embedding模型管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools_manage_embedding.py list                    # 列出可用模型
  python tools_manage_embedding.py download bge-small-zh   # 下载模型
  python tools_manage_embedding.py reset                   # 清理向量数据库
  python tools_manage_embedding.py test bge-small-zh       # 测试模型效果
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # list 命令
    subparsers.add_parser("list", help="列出可用模型")
    
    # download 命令
    download_parser = subparsers.add_parser("download", help="下载模型")
    download_parser.add_argument("model", help="模型别名 (如: bge-small-zh)")
    
    # reset 命令
    subparsers.add_parser("reset", help="清理向量数据库（更换模型后必须执行）")
    
    # test 命令
    test_parser = subparsers.add_parser("test", help="测试模型效果")
    test_parser.add_argument("model", help="模型别名 (如: bge-small-zh)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == "list":
        list_models()
    elif args.command == "download":
        download_model(args.model)
    elif args.command == "reset":
        reset_vector_db()
    elif args.command == "test":
        test_query(args.model)


if __name__ == "__main__":
    main()
