# -*- coding: utf-8 -*-
"""
BM25 稀疏检索引擎 — 纯 Python，零外部依赖。

算法核心移植自 MODULAR-RAG-MCP-SERVER 的 bm25_indexer.py，
适配音乐库场景：document = 单首歌的文本（artist + title + album + genre + language）。

中文分词策略：空格分词 + 2-gram 字组，兼顾精确匹配和子串召回。
"""
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def compute_idf(N: int, df: int) -> float:
    """BM25 IDF 计算公式。N=总文档数, df=包含该词的文档数。"""
    return math.log((N - df + 0.5) / (df + 0.5) + 1.0)


def compute_bm25_score(
    tf: int,
    doc_len: int,
    avg_doc_len: float,
    idf: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """BM25 单 term 得分。

    tf: term 在本文档中的出现次数
    doc_len: 本文档的词数
    avg_doc_len: 所有文档的平均词数
    idf: 逆文档频率
    """
    length_norm = 1 - b + b * (doc_len / max(avg_doc_len, 1))
    return idf * (tf * (k1 + 1)) / (tf + k1 * length_norm)


def _tokenize(text: str) -> List[str]:
    """中文友好的分词：空格分割 + 2-gram 字组。

    例如 "周杰伦 晴天 国语" →
      ["周杰伦", "晴天", "国语", "周杰", "杰伦", "晴", "天", "国", "语"]
    2-gram 保证单字查询（如"伦"）也能部分匹配。
    """
    tokens = []
    # 空格分词
    parts = text.split()
    for part in parts:
        tokens.append(part)
        if len(part) >= 2:
            for i in range(len(part) - 1):
                tokens.append(part[i:i + 2])
            # 单字也加入
            for ch in part:
                tokens.append(ch)
    return tokens


class BM25Index:
    """轻量 BM25 倒排索引。

    使用方式:
        idx = BM25Index()
        idx.build([{"id": "abc", "text": "周杰伦 晴天 国语 流行"}, ...])
        results = idx.search("周杰伦", top_k=10)
        # → [("abc", 12.5), ("def", 8.3), ...]
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._index: Dict[str, dict] = {}      # term → {idf, df, postings: {doc_id: [positions]}}
        self._doc_lengths: Dict[str, int] = {}  # doc_id → token count
        self._avg_doc_len: float = 0.0
        self._doc_count: int = 0

    def build(self, documents: List[dict]) -> None:
        """从文档列表构建倒排索引。

        Args:
            documents: [{"id": str, "text": str}, ...]
        """
        self._index.clear()
        self._doc_lengths.clear()
        self._doc_count = len(documents)

        if self._doc_count == 0:
            self._avg_doc_len = 0.0
            return

        # 第一遍：统计词频和文档频率
        term_doc_freq: Dict[str, int] = {}
        total_tokens = 0

        for doc in documents:
            doc_id = doc["id"]
            text = doc.get("text", "")
            tokens = _tokenize(text)
            self._doc_lengths[doc_id] = len(tokens)
            total_tokens += len(tokens)

            # 本文档内词频
            tf_map: Dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            # 更新倒排索引
            for term, tf in tf_map.items():
                if term not in self._index:
                    self._index[term] = {"df": 0, "postings": {}}
                self._index[term]["postings"][doc_id] = tf
                term_doc_freq[term] = term_doc_freq.get(term, 0) + 1

        self._avg_doc_len = total_tokens / self._doc_count

        # 第二遍：计算每个 term 的 IDF 和 df
        for term, info in self._index.items():
            df = term_doc_freq.get(term, 0)
            info["df"] = df
            info["idf"] = compute_idf(self._doc_count, df)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """BM25 检索，返回 [(doc_id, bm25_score), ...]，按分数降序。

        Args:
            query: 查询字符串（如 "周杰伦 国语"）
            top_k: 返回结果数
        """
        if not self._index:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # 计算每个候选文档的 BM25 总分
        doc_scores: Dict[str, float] = {}

        for token in query_tokens:
            if token not in self._index:
                continue
            info = self._index[token]
            idf = info["idf"]
            for doc_id, tf in info["postings"].items():
                doc_len = self._doc_lengths.get(doc_id, 1)
                term_score = compute_bm25_score(
                    tf=tf,
                    doc_len=doc_len,
                    avg_doc_len=self._avg_doc_len,
                    idf=idf,
                    k1=self.k1,
                    b=self.b,
                )
                doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + term_score

        # 排序返回
        ranked = sorted(doc_scores.items(), key=lambda x: -x[1])
        return ranked[:top_k]

    def save(self, filepath: str) -> None:
        """将索引序列化为 JSON 文件。"""
        data = {
            "k1": self.k1,
            "b": self.b,
            "doc_count": self._doc_count,
            "avg_doc_len": self._avg_doc_len,
            "index": {},
            "doc_lengths": self._doc_lengths,
        }
        for term, info in self._index.items():
            data["index"][term] = {
                "df": info["df"],
                "idf": info["idf"],
                "postings": info["postings"],
            }
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self, filepath: str) -> bool:
        """从 JSON 文件加载索引。成功返回 True，文件不存在返回 False。"""
        p = Path(filepath)
        if not p.exists():
            return False
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.k1 = data.get("k1", 1.5)
        self.b = data.get("b", 0.75)
        self._doc_count = data.get("doc_count", 0)
        self._avg_doc_len = data.get("avg_doc_len", 0.0)
        self._doc_lengths = data.get("doc_lengths", {})
        self._index = data.get("index", {})
        return True

    @property
    def doc_count(self) -> int:
        return self._doc_count

    @property
    def term_count(self) -> int:
        return len(self._index)
