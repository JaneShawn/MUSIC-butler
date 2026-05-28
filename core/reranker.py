# -*- coding: utf-8 -*-
"""
Cross-Encoder 精排模块 — 对 Hybrid Search 的 Top-K 候选做精细重排。

移植自 MODULAR-RAG-MCP-SERVER 的 cross_encoder_reranker.py，
策略：Cross-Encoder 对 (query, document) 逐对打分，比 Dense/BM25 更精准，
但成本更高，所以只对 Top-20 候选做，不对全库。

优雅降级：sentence-transformers 未安装时，rerank() 原样返回候选。
"""
from typing import Dict, List, Optional


class CrossEncoderReranker:
    """Cross-Encoder 精排器。

    使用方式:
        reranker = CrossEncoderReranker()
        ranked = reranker.rerank("国语抒情歌", candidates, top_k=5)
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        timeout: float = 10.0,
    ):
        self._model_name = model_name
        self._timeout = timeout
        self._model = None
        self._available = None  # None = 未检测

    @property
    def is_available(self) -> bool:
        """Cross-Encoder 模型是否可用。"""
        if self._available is None:
            self._available = self._try_load()
        return self._available

    def _try_load(self) -> bool:
        """尝试加载 Cross-Encoder 模型。成功返回 True，失败返回 False。"""
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            return True
        except Exception:
            return False

    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_k: int = 5,
    ) -> List[Dict]:
        """对候选集重排序。

        Args:
            query: 查询字符串
            candidates: 候选列表，每项需含 "document" 或 "text" 字段
            top_k: 返回数量

        Returns:
            按 Cross-Encoder 分数降序排列的候选（每项附加 "rerank_score" 字段）
        """
        if not candidates:
            return []

        if not self.is_available:
            # 优雅降级：原样返回
            return candidates[:top_k]

        try:
            return self._do_rerank(query, candidates, top_k)
        except Exception:
            return candidates[:top_k]

    def _do_rerank(self, query: str, candidates: List[Dict], top_k: int) -> List[Dict]:
        """执行 Cross-Encoder 打分和排序。"""
        # 提取文本
        texts = []
        for c in candidates:
            text = c.get("document") or c.get("text") or ""
            texts.append(text)

        if not texts:
            return candidates[:top_k]

        # 构建 (query, passage) 对
        pairs = [(query, text) for text in texts]

        # Cross-Encoder 批量打分
        scores = self._model.predict(pairs, show_progress_bar=False)

        # 将分数附加到候选并排序
        scored = []
        for i, c in enumerate(candidates):
            c_copy = dict(c)
            c_copy["rerank_score"] = float(scores[i]) if i < len(scores) else 0.0
            scored.append(c_copy)

        scored.sort(key=lambda x: -x.get("rerank_score", 0.0))
        return scored[:top_k]
