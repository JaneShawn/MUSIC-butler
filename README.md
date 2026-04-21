# Music Agent - 智能音乐库管理系统

一个基于多Agent架构的智能音乐库管理工具，支持本地音乐库RAG检索、自动发现新音乐、智能推荐等功能。

## 🎯 功能特性

### Librarian Agent（图书管理员）
- 📁 自动扫描本地音乐库
- 🔊 音频指纹识别与元数据补全
- 🔍 基于RAG的自然语言查询（支持"适合下雨听的国语歌"等语义搜索）
- 📊 音乐库统计分析

### Scout Agent（侦察兵）
- 📡 RSS订阅监控
- 🌐 Reddit音乐社区追踪
- 🔗 新音乐自动发现

### Curator Agent（策展人）
- 🎯 基于偏好的智能推荐
- 📈 个性化评分系统
- 📰 每周音乐发现报告

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境

复制配置文件并修改：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写必要的API密钥（可选）：

```bash
# Kimi API（用于LLM生成描述）
KIMI_API_KEY=your_key_here

# Reddit API（用于Scout Agent）
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret

# AcoustID（用于音频指纹识别）
ACOUSTID_API_KEY=your_key_here
```

编辑 `config.yaml` 配置你的音乐库路径：

```yaml
library:
  path: "C:\\Users\\YourName\\Music"  # 修改为你的音乐文件夹路径
```

### 3. 使用命令行

```bash
# 扫描音乐库
python main.py scan

# 自然语言查询
python main.py query "周杰伦的歌"
python main.py query "适合下雨听的国语歌"

# 发现新音乐
python main.py discover

# 生成周报
python main.py report
```

### 4. 启动Web界面

```bash
python main.py web
```

访问 http://localhost:8501 查看Web界面。

## 📁 项目结构

```
music-agent/
├── agents/              # Agent实现
│   ├── base_agent.py    # 基类
│   ├── librarian.py     # 图书管理员
│   ├── scout.py         # 侦察兵
│   └── curator.py       # 策展人
├── core/                # 核心模块
│   ├── vector_store.py  # ChromaDB封装
│   ├── audio_fingerprint.py
│   └── metadata_fetcher.py
├── web/                 # Web界面
│   └── app.py           # Streamlit应用
├── tasks/               # 定时任务
├── data/                # 数据存储
│   └── chroma/          # 向量数据库
├── main.py              # CLI入口
├── config.yaml          # 配置文件
├── requirements.txt
└── README.md
```

## ⚙️ 配置说明

### config.yaml

```yaml
library:
  path: "/path/to/your/music"      # 音乐库路径
  supported_formats: [".flac", ".mp3", ".wav", ".m4a"]

rag:
  embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
  top_k: 10

scout:
  rss_feeds:                        # RSS数据源
    - "https://example.com/feed.xml"
  reddit_subs:                      # Reddit社区
    - "indieheads"
    - "hiphopheads"
  check_interval_hours: 24
```

## 💡 使用示例

### RAG查询示例

```python
from agents import LibrarianAgent

librarian = LibrarianAgent(config)
librarian.run("scan")

# 自然语言查询
results = librarian.query("90年代的粤语摇滚")
for item in results:
    print(f"{item['song'].title} - {item['song'].artist}")
```

### 音乐发现流程

```python
from agents import LibrarianAgent, ScoutAgent, CuratorAgent

# 初始化Agent
librarian = LibrarianAgent(config)
scout = ScoutAgent(config)
curator = CuratorAgent(config, librarian)

# 1. 确保音乐库已扫描
librarian.run("scan")

# 2. 发现新音乐
candidates = scout.run("all")

# 3. 生成推荐
recommendations = curator.run("evaluate", candidates=candidates)

for rec in recommendations:
    print(f"{rec.candidate.artist} - {rec.candidate.title}")
    print(f"推荐理由: {rec.match_reason}")
```

## 🔧 技术栈

- **Agent架构**: 自定义多Agent协作框架
- **向量数据库**: ChromaDB
- **Embedding**: Sentence-Transformers
- **音频处理**: librosa, pyacoustid, mutagen
- **Web界面**: Streamlit
- **数据源**: MusicBrainz API, Reddit API, RSS

## 📄 简历亮点

- 设计并实现多Agent协作架构（Librarian/Scout/Curator）
- 构建RAG系统，支持自然语言语义检索
- 集成音频指纹技术实现歌曲精准识别
- 实现个性化推荐算法与反馈学习机制
- 使用向量数据库（ChromaDB）进行高效相似度搜索

## 📝 License

MIT License
