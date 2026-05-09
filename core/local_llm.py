"""
Local LLM - 本地大模型接口
使用Ollama，无需API key
"""
import subprocess
import json
from typing import Optional


class LocalLLM:
    """
    本地LLM封装（Ollama）
    """
    
    def __init__(self, model: str = "qwen2.5:3b"):
        self.model = model
        self.available = self._check_ollama()
    
    def _check_ollama(self) -> bool:
        """检查Ollama是否安装"""
        try:
            subprocess.run(["ollama", "--version"], 
                         capture_output=True, check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """
        生成文本
        
        如果Ollama未安装，返回基于规则的fallback
        """
        if not self.available:
            return self._fallback_generate(prompt)
        
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            result = subprocess.run(
                ["ollama", "run", self.model, json.dumps(messages)],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            return result.stdout.strip()
            
        except Exception as e:
            return self._fallback_generate(prompt)
    
    def _fallback_generate(self, prompt: str) -> str:
        """
        无LLM时的fallback实现
        虽然简单，但体现Agent意图理解的设计
        """
        # 简单的关键词匹配
        if "推荐" in prompt or "recommend" in prompt.lower():
            return "根据你的音乐库分析，推荐以下风格相似的歌曲..."
        elif "查询" in prompt or "query" in prompt.lower():
            return "正在分析查询意图..."
        else:
            return "已接收指令，正在处理..."
    
    def analyze_query_intent(self, query: str) -> dict:
        """
        分析查询意图 - Agent的核心能力
        
        把自然语言转换成结构化查询
        例如："90年代的粤语摇滚" -> {"year": "1990-1999", "genre": "摇滚", "language": "粤语"}
        """
        system_prompt = """你是一个音乐查询理解助手。
分析用户的查询，提取以下维度：
- 艺术家 (artist)
- 流派 (genre)  
- 年代/年份 (year)
- 情绪/场景 (mood)
- 语言 (language)

返回JSON格式。"""

        prompt = f"用户查询: {query}\n请分析查询意图，返回JSON。"
        
        response = self.generate(prompt, system=system_prompt)
        
        # 尝试解析JSON
        try:
            # 提取JSON部分
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        
        # Fallback：简单关键词提取
        return self._simple_intent_extraction(query)
    
    def _simple_intent_extraction(self, query: str) -> dict:
        """简单的意图提取（无需LLM）"""
        intent = {
            "original_query": query,
            "artist": None,
            "genre": None,
            "year": None,
            "mood": None,
            "language": None
        }
        
        # 关键词匹配
        mood_keywords = {
            "安静": "calm", "安静": "calm", "sleep": "calm",
            "摇滚": "rock", "rock": "rock", 
            "轻快": "upbeat", "开心": "happy",
            "伤感": "sad", "难过": "sad", "sad": "sad",
            "下雨": "rainy", "rain": "rainy", "雨": "rainy"
        }
        
        for keyword, mood in mood_keywords.items():
            if keyword in query.lower():
                intent["mood"] = mood
                break
        
        # 年份匹配
        import re
        year_match = re.search(r'(\d{2,4})s?', query)
        if year_match:
            year = int(year_match.group(1))
            if year < 100:
                year = 1900 + year if year >= 50 else 2000 + year
            intent["year"] = year
        
        return intent
    
    def generate_recommendation_reason(self, candidate: dict, user_library: dict) -> str:
        """
        生成推荐理由 - 体现Curator Agent的智能
        
        分析候选歌曲与用户库的关联，生成自然语言描述
        """
        prompt = f"""候选歌曲: {candidate['artist']} - {candidate['title']}
用户已有相似歌曲: {user_library.get('similar_songs', [])}

请生成一句简短的推荐理由（30字以内），说明为什么这首歌适合推荐。"""

        response = self.generate(prompt)
        
        # 清理响应
        reason = response.strip().replace('"', '').replace("'", "")
        if len(reason) > 50:
            reason = reason[:50] + "..."
        
        return reason if reason else f"与你收藏的{candidate.get('genre', '歌曲')}风格相似"


def setup_ollama():
    """
    引导用户安装Ollama
    """
    print("""
要使用本地LLM功能，请先安装Ollama:

1. 下载安装: https://ollama.com/download
2. 拉取模型: ollama pull qwen2.5:3b
3. 重新运行程序

或者继续使用简化版本（功能受限）
""")
