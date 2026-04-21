"""
Kimi API 客户端
"""
import os
import json
from typing import Optional, List, Dict, Any
import httpx


class KimiClient:
    """
    Kimi API 客户端封装
    """
    
    BASE_URL = "https://api.moonshot.cn/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("KIMI_API_KEY not found. Please set it in .env file")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.model = "moonshot-v1-8k"
    
    def chat(self, 
             messages: List[Dict[str, str]], 
             temperature: float = 0.7,
             max_tokens: int = 1000,
             retries: int = 3) -> str:
        """
        调用Kimi聊天接口（带重试）
        """
        import time
        
        for attempt in range(retries):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        f"{self.BASE_URL}/chat/completions",
                        headers=self.headers,
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens
                        }
                    )
                    
                    # 处理限流
                    if response.status_code == 429:
                        wait_time = 2 ** attempt  # 指数退避
                        print(f"API限流，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    
                    response.raise_for_status()
                    
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < retries - 1:
                    continue
                print(f"Kimi API HTTP error: {e}")
                return ""
            except Exception as e:
                print(f"Kimi API error: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return ""
        
        return ""
    
    def generate(self, 
                 prompt: str, 
                 system: Optional[str] = None,
                 **kwargs) -> str:
        """
        简化的生成接口
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        return self.chat(messages, **kwargs)
    
    def analyze_query_intent(self, query: str) -> Dict[str, Any]:
        """
        分析查询意图
        把自然语言转换成结构化条件
        """
        system_prompt = """你是一个音乐查询理解专家。

分析用户的自然语言查询，提取以下维度（如未提及则为null）：
- artist: 艺术家名字
- genre: 音乐流派（如：摇滚、流行、说唱、爵士等）
- year_range: 年代（如：1990s, 2000-2010, 80年代）
- mood: 情绪/场景（如：安静、开心、伤感、下雨、运动等）
- language: 语言（如：国语、粤语、英语、日语等）

必须返回JSON格式，不要其他文字。"""

        prompt = f"用户查询: \"{query}\"\n\n请分析并返回JSON:"
        
        response = self.generate(prompt, system=system_prompt, temperature=0.3)
        
        # 提取JSON（使用非贪婪匹配，避免跨代码块捕获）
        try:
            import re
            # 先尝试直接解析整个响应
            response_clean = response.strip()
            if response_clean.startswith('{') and response_clean.endswith('}'):
                return json.loads(response_clean)
            # 否则从文本中提取第一个 JSON 块
            json_match = re.search(r'\{[\s\S]*?\}', response)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            pass
        
        return {"original_query": query}
    
    def generate_recommendation_reason(self, 
                                      candidate: Dict, 
                                      user_preferences: Dict) -> str:
        """
        生成推荐理由
        
        Args:
            candidate: 候选歌曲信息
            user_preferences: 用户偏好（流派、艺术家等）
        """
        system_prompt = """你是音乐推荐专家，擅长生成个性化推荐理由。

规则：
1. 简短有力，20-30字
2. 指出具体相似点（如：吉他riff、鼓点、唱腔等）
3. 用自然的口吻，像朋友推荐

示例：
- "这首歌的吉他riff很像你收藏的《挪威的森林》，氛围感很强"
- "同样是90年代粤语金曲，林夕的词+陈辉阳的曲"
- "和你常听的R&B风格接近，副歌旋律很抓耳"""

        prompt = f"""候选歌曲:
- 歌名: {candidate.get('title')}
- 艺术家: {candidate.get('artist')}
- 流派: {candidate.get('genre', '未知')}
- 专辑: {candidate.get('album', '未知')}

用户偏好:
- 常听流派: {user_preferences.get('top_genres', [])}
- 常听艺术家: {user_preferences.get('top_artists', [])}

请生成一句推荐理由:"""

        response = self.generate(
            prompt, 
            system=system_prompt,
            temperature=0.8,
            max_tokens=100
        )
        
        # 清理响应
        reason = response.strip().replace('"', '').replace("'", "")
        if len(reason) > 60:
            reason = reason[:60] + "..."
        
        return reason if reason else f"与你常听的{candidate.get('genre', '歌曲')}风格相似"
    
    def generate_weekly_summary(self, discoveries: List[Dict]) -> str:
        """
        生成周报摘要
        """
        system_prompt = """你是音乐周报编辑，用轻松的口吻总结本周音乐发现。

要求：
1. 3-4句话
2. 提及发现的数量和亮点
3. 像给朋友发的消息

示例：
"本周发现了5首你可能会喜欢的歌！有一首90年代的粤语老歌特别抓耳，
和你常听的Beyond风格很像。还有一首独立摇滚，吉他的音色很棒。"""

        # 构造发现列表
        songs_text = "\n".join([
            f"- {d.get('artist')}《{d.get('title')}》（{d.get('genre', '未知流派')}）"
            for d in discoveries[:5]
        ])
        
        prompt = f"""本周发现的歌曲（共{len(discoveries)}首）:
{songs_text}

请生成周报摘要:"""

        return self.generate(prompt, system=system_prompt, max_tokens=200)
