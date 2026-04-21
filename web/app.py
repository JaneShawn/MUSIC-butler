"""
Streamlit Web App - 音乐库管理界面
"""
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 加载.env
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import yaml
from datetime import datetime

from agents import LibrarianAgent, ScoutAgent, CuratorAgent, OrganizerAgent


# 页面配置
st.set_page_config(
    page_title="Music Agent",
    page_icon="🎵",
    layout="wide"
)

# 加载配置
@st.cache_resource
def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()

# 初始化Agent（缓存）
@st.cache_resource
def init_agents(_config):
    librarian = LibrarianAgent(_config)
    scout = ScoutAgent(_config)
    curator = CuratorAgent(_config, librarian)
    organizer = OrganizerAgent(_config, librarian)
    return librarian, scout, curator, organizer

librarian, scout, curator, organizer = init_agents(config)


# 侧边栏导航
st.sidebar.title("🎵 Music Agent")
page = st.sidebar.radio("导航", ["首页", "音乐库", "发现", "周报", "整理"])


# 首页
if page == "首页":
    st.title("Music Agent - 智能音乐库管理")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(label="音乐库", value=f"{librarian.get_stats()['total_songs']} 首")
    
    with col2:
        st.metric(label="艺术家", value=f"{librarian.get_stats()['artists']} 位")
    
    with col3:
        st.metric(label="专辑", value=f"{librarian.get_stats()['albums']} 张")
    
    st.divider()
    
    st.subheader("快速操作")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 扫描音乐库", use_container_width=True):
            with st.spinner("正在扫描..."):
                result = librarian.run("scan")
                st.success(f"扫描完成！发现 {result['new_songs']} 首新歌")
                st.info(f"总计：{result['total_indexed']} 首")
    
    with col2:
        if st.button("🔍 发现新音乐", use_container_width=True):
            with st.spinner("正在搜索..."):
                candidates = scout.run("all")
                if candidates:
                    recommendations = curator.run("evaluate", candidates=candidates)
                    st.success(f"发现 {len(recommendations)} 首推荐")
                    st.session_state["latest_recommendations"] = recommendations
                else:
                    st.warning("暂时没有发现新音乐")


# 音乐库页面
elif page == "音乐库":
    st.title("我的音乐库")
    
    # 搜索
    query = st.text_input("搜索歌曲（支持自然语言）", 
                         placeholder="例如：周杰伦的歌、适合下雨听的国语歌")
    
    if query:
        results = librarian.query(query, top_k=10)
        
        if results:
            st.write(f"找到 {len(results)} 首相关歌曲：")
            
            for i, item in enumerate(results):
                song = item["song"]
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{song.title}** - {song.artist}")
                        st.caption(f"专辑: {song.album} | 流派: {song.genre or '未知'}")
                    with col2:
                        st.progress(item["similarity"], text=f"匹配度: {item['similarity']:.1%}")
                    st.divider()
        else:
            st.info("没有找到匹配的歌曲")
    else:
        # 显示统计
        stats = librarian.get_stats()
        
        st.subheader("库统计")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总歌曲", stats["total_songs"])
        col2.metric("艺术家", stats["artists"])
        col3.metric("专辑", stats["albums"])
        col4.metric("流派", stats["genres"])


# 发现页面
elif page == "发现":
    st.title("🔍 音乐发现")
    
    source = st.selectbox("数据源", ["all", "rss", "reddit"])
    
    if st.button("开始搜索", type="primary"):
        with st.spinner("侦察兵正在工作..."):
            candidates = scout.run(source)
            
            if candidates:
                recommendations = curator.run("evaluate", candidates=candidates)
                
                st.success(f"发现 {len(candidates)} 首候选，{len(recommendations)} 首推荐")
                
                for rec in recommendations:
                    with st.container():
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**{rec.candidate.title}** - {rec.candidate.artist}")
                            st.caption(f"来源: {rec.candidate.source}")
                            st.write(f"💡 {rec.match_reason}")
                        with col2:
                            st.badge(rec.action.replace("_", " ").title())
                            st.write(f"相似度: {rec.similarity_score:.2f}")
                        st.divider()
            else:
                st.info("没有发现新音乐")


# 周报页面
elif page == "周报":
    st.title("📊 每周音乐报告")
    
    # 获取推荐记录（简化版，实际应该持久化存储）
    if "latest_recommendations" in st.session_state:
        recs = st.session_state["latest_recommendations"]
        report = curator.run("report", recommendations=recs)
        
        st.header(report["title"])
        
        # 概览
        summary = report["summary"]
        
        col1, col2, col3 = st.columns(3)
        col1.metric("本周发现", summary["total_discovered"])
        col2.metric("强烈推荐", summary["highly_recommended"])
        col3.metric("涉及流派", len(summary["genres"]))
        
        st.divider()
        
        # 推荐列表
        st.subheader("本周推荐")
        
        for rec in report["recommendations"]:
            with st.expander(f"{rec['artist']} - {rec['title']}"):
                st.write(f"**流派**: {', '.join(rec['genre'])}")
                st.write(f"**推荐理由**: {rec['reason']}")
                st.write(f"**来源**: {rec['source']}")
                st.write(f"**匹配度**: {rec['score']}")
    else:
        st.info("还没有生成报告，先去【发现】页面搜索新音乐吧！")


# 整理页面
elif page == "整理":
    st.title("📁 音乐文件整理")
    
    # 分析当前结构
    st.subheader("📊 当前目录分析")
    
    if st.button("分析当前结构"):
        with st.spinner("正在分析..."):
            analysis = organizer.run("analyze")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("总歌曲", analysis["total_songs"])
            col2.metric("艺术家数", analysis["artists_count"])
            col3.metric("流派数", analysis["genres_count"])
            
            st.info(f"💡 推荐整理策略: **{analysis['suggestion']}**")
            
            # 显示TOP艺术家
            st.subheader("最常听的艺术家")
            top_artists = analysis["top_artists"][:5]
            for artist, count in top_artists:
                st.write(f"- {artist}: {count}首")
    
    st.divider()
    
    # 整理功能
    st.subheader("🗂️ 执行整理")
    
    strategy = st.selectbox(
        "整理策略",
        ["artist/album", "artist", "album", "genre", "year", "genre/artist", "year/artist"],
        help="选择文件分类方式"
    )
    
    col1, col2 = st.columns(2)
    with col1:
        dry_run = st.checkbox("仅预览（不实际移动文件）", value=True)
    with col2:
        keep_original = st.checkbox("保留原文件（复制而非移动）")
    
    if st.button("生成整理计划", type="primary"):
        with st.spinner("正在生成计划..."):
            from agents.organizer import OrganizeStrategy
            plan = organizer.run("plan", strategy=OrganizeStrategy(strategy))
            preview = organizer.preview_plan(plan)
            
            # 保存到session
            st.session_state["organize_plan"] = plan
            st.session_state["organize_preview"] = preview
            
            summary = preview["summary"]
            
            st.success("计划生成完成！")
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("总文件", summary["total_files"])
            col2.metric("将移动", summary["to_move"])
            col3.metric("将复制", summary["to_copy"])
            col4.metric("跳过", summary["skip"])
            
            if summary["conflicts"] > 0:
                st.warning(f"⚠️ 检测到 {summary['conflicts']} 个文件名冲突（将自动重命名）")
            
            # 显示示例
            st.subheader("整理示例")
            for ex in preview["examples"][:3]:
                st.code(f"{ex['action'].upper()}: {Path(ex['from']).name}\n  → {Path(ex['to']).name}")
    
    # 执行按钮
    if "organize_plan" in st.session_state:
        if dry_run:
            st.info("☝️ 当前为预览模式，实际文件不会被移动。取消'仅预览'选项后可执行整理。")
        else:
            if st.button("🚀 执行整理", type="primary"):
                with st.spinner("正在整理文件..."):
                    plan = st.session_state["organize_plan"]
                    result = organizer.run("execute", plan=plan, dry_run=False)
                    
                    st.success(f"整理完成！成功: {result.executed}, 失败: {result.failed}")
                    
                    if result.failed > 0:
                        with st.expander("查看失败的文件"):
                            for detail in result.details:
                                if detail["status"] == "failed":
                                    st.error(f"{detail['from']}: {detail.get('error', 'Unknown')}")


# 页脚
st.sidebar.divider()
st.sidebar.caption("Music Agent v1.0")
