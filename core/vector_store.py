"""
Vector Store - ChromaDB封装（智能回退版）
自动检测 sentence-transformers，如不可用则使用ChromaDB默认embedding

[Phase 6] Hybrid Search: Dense (ChromaDB) + Sparse (BM25) + RRF Fusion
"""
from typing import List, Dict, Optional, Any, Tuple
import chromadb
from chromadb.config import Settings
from core.sparse_retriever import BM25Index


# 支持的中文Embedding模型配置
EMBEDDING_MODELS = {
    "bge-small-zh": "BAAI/bge-small-zh-v1.5",
    "bge-large-zh": "BAAI/bge-large-zh-v1.5",
    "bge-base-zh": "BAAI/bge-base-zh-v1.5",
    "paraphrase-multilingual": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "all-MiniLM": "sentence-transformers/all-MiniLM-L6-v2",
}

# 全局标记：是否使用外部embedding模型
_EXTERNAL_EMBEDDING_AVAILABLE = None
_EXTERNAL_EMBEDDING_FUNC = None
_EXTERNAL_EMBEDDING_MODEL = None  # 缓存当前模型名，用于切换检测


def _check_sentence_transformers():
    """检查 sentence_transformers 是否可用"""
    global _EXTERNAL_EMBEDDING_AVAILABLE
    if _EXTERNAL_EMBEDDING_AVAILABLE is not None:
        return _EXTERNAL_EMBEDDING_AVAILABLE
    
    try:
        import sentence_transformers
        _EXTERNAL_EMBEDDING_AVAILABLE = True
        print("[OK] sentence-transformers installed")
        return True
    except ImportError:
        _EXTERNAL_EMBEDDING_AVAILABLE = False
        print("[WARN] sentence-transformers not installed, using ChromaDB default")
        print("       Install with: pip install sentence-transformers")
        return False


def get_embedding_function(model_name: str = None, device: str = "cpu"):
    """
    获取Embedding函数（自动回退，支持模型切换）
    
    Returns:
        ChromaDB embedding function 或 None（使用默认）
    """
    global _EXTERNAL_EMBEDDING_FUNC, _EXTERNAL_EMBEDDING_MODEL
    
    # 如果不可用，直接返回None（使用ChromaDB默认）
    if not _check_sentence_transformers():
        return None
    
    # 解析模型名称
    if model_name in EMBEDDING_MODELS:
        model_name = EMBEDDING_MODELS[model_name]
    elif model_name is None:
        model_name = EMBEDDING_MODELS["bge-small-zh"]
    
    # 如果已经初始化过且模型未变更，直接返回
    if _EXTERNAL_EMBEDDING_FUNC is not None and _EXTERNAL_EMBEDDING_MODEL == model_name:
        return _EXTERNAL_EMBEDDING_FUNC
    
    # 模型变更或首次加载
    if _EXTERNAL_EMBEDDING_FUNC is not None and _EXTERNAL_EMBEDDING_MODEL != model_name:
        print(f"🔄 模型切换: {_EXTERNAL_EMBEDDING_MODEL or 'None'} → {model_name}")
        _EXTERNAL_EMBEDDING_FUNC = None
    
    try:
        from chromadb.utils import embedding_functions
        print(f"🔄 加载Embedding模型: {model_name}")
        
        _EXTERNAL_EMBEDDING_FUNC = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name,
            device=device
        )
        _EXTERNAL_EMBEDDING_MODEL = model_name
        return _EXTERNAL_EMBEDDING_FUNC
        
    except Exception as e:
        print(f"⚠️  加载模型失败: {e}")
        print("   回退到ChromaDB默认embedding")
        _EXTERNAL_EMBEDDING_FUNC = None
        _EXTERNAL_EMBEDDING_MODEL = None
        return None


class VectorStore:
    """
    向量数据库封装（智能回退版）
    - 有sentence-transformers: 使用高质量中文模型
    - 无sentence-transformers: 使用ChromaDB默认embedding
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.persist_dir = config.get("persist_directory", "./data/chroma")
        self.collection_name = config.get("collection_name", "music_library")

        # 模型配置
        self.model_name = config.get("embedding_model", "bge-small-zh")
        self.device = config.get("device", "cpu")
        self.use_external_embedding = _check_sentence_transformers()

        # Hybrid search 配置
        hybrid_cfg = config.get("hybrid", {})
        self.hybrid_enabled = hybrid_cfg.get("enabled", True)
        self.rrf_k = hybrid_cfg.get("rrf_k", 60)
        self.sparse_weight = hybrid_cfg.get("sparse_weight", 1.0)
        self.dense_weight = hybrid_cfg.get("dense_weight", 1.0)

        # 初始化Embedding函数（如果可用）
        if self.use_external_embedding:
            self.embedding_func = get_embedding_function(
                model_name=self.model_name,
                device=self.device
            )
            self.use_external_embedding = self.embedding_func is not None
        else:
            self.embedding_func = None

        # 初始化ChromaDB
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )

        # 获取或创建集合
        if self.use_external_embedding and self.embedding_func:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_func,
                metadata={"hnsw:space": "cosine"}
            )
        else:
            # 使用ChromaDB默认embedding
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )

        # BM25 稀疏索引
        self.bm25 = BM25Index()
        self._bm25_loaded = False
        bm25_path = config.get("bm25_index_path", "./data/bm25_index.json")
        if self.bm25.load(bm25_path):
            self._bm25_loaded = True

        mode_str = f"外部模型({self.model_name})" if self.use_external_embedding else "ChromaDB默认"
        hybrid_str = "+BM25" if self._bm25_loaded else ""
        print(f"[OK] VectorStore initialized | Mode: {mode_str}{hybrid_str} | Documents: {self.count()}")
    
    def add(self, texts: List[str], ids: List[str], metadatas: Optional[List[Dict]] = None):
        """添加文档到向量库"""
        self.collection.add(
            documents=texts,
            ids=ids,
            metadatas=metadatas
        )
    
    def search(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """混合搜索：Dense (ChromaDB) + Sparse (BM25) + RRF Fusion。

        如果 BM25 索引可用，并行跑两路检索并用 RRF 融合。
        否则回退到纯 Dense 检索。
        """
        # 纯 Dense 作为 baseline
        dense_results = self._dense_search(query, top_k=top_k * 2, filters=filters)

        # 如果没有 BM25 索引，直接返回 Dense 结果
        if not self._bm25_loaded or not self.hybrid_enabled:
            return dense_results[:top_k]

        # Sparse 检索
        sparse_results = self._sparse_search(query, top_k=top_k * 2)

        # RRF 融合
        fused = self._rrf_fusion(dense_results, sparse_results, top_k=top_k)
        return fused

    def _dense_search(self, query: str, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """纯 Dense 检索（ChromaDB 语义搜索）。"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=filters
        )

        formatted = []
        for i in range(len(results["ids"][0])):
            formatted.append({
                "id": results["ids"][0][i],
                "score": max(0.0, 1 - results["distances"][0][i] / 2),
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            })
        return formatted

    def _sparse_search(self, query: str, top_k: int = 10) -> List[Dict]:
        """BM25 稀疏检索，返回与 _dense_search 相同格式的 List[Dict]。"""
        raw = self.bm25.search(query, top_k=top_k)
        formatted = []
        for doc_id, score in raw:
            # 从 ChromaDB 取文本和元数据
            try:
                record = self.collection.get(ids=[doc_id])
                document = record["documents"][0] if record.get("documents") else ""
                metadata = record["metadatas"][0] if record.get("metadatas") else {}
            except Exception:
                document = ""
                metadata = {}
            formatted.append({
                "id": doc_id,
                "score": score,
                "document": document,
                "metadata": metadata,
            })
        return formatted

    def _rrf_fusion(
        self,
        dense_results: List[Dict],
        sparse_results: List[Dict],
        top_k: int = 10,
    ) -> List[Dict]:
        """RRF (Reciprocal Rank Fusion) 融合 Dense 和 Sparse 结果。

        公式：RRF_score(d) = w_dense/(k + rank_dense) + w_sparse/(k + rank_sparse)
        """
        k = self.rrf_k
        w_d = self.dense_weight
        w_s = self.sparse_weight
        scores: Dict[str, Tuple[float, Dict]] = {}

        # Dense 路
        for rank, item in enumerate(dense_results, start=1):
            doc_id = item["id"]
            rrf = w_d / (k + rank)
            if doc_id in scores:
                scores[doc_id] = (scores[doc_id][0] + rrf, scores[doc_id][1])
            else:
                scores[doc_id] = (rrf, item)

        # Sparse 路
        for rank, item in enumerate(sparse_results, start=1):
            doc_id = item["id"]
            rrf = w_s / (k + rank)
            if doc_id in scores:
                scores[doc_id] = (scores[doc_id][0] + rrf, scores[doc_id][1])
            else:
                scores[doc_id] = (rrf, item)

        # 按 RRF 分数降序排列
        ranked = sorted(scores.items(), key=lambda x: -x[0][0])
        result = []
        for doc_id, (rrf_score, item) in ranked[:top_k]:
            item["score"] = round(rrf_score, 6)
            result.append(item)
        return result

    def build_bm25_index(self, documents: List[dict]) -> None:
        """从文档列表构建 BM25 索引并持久化。

        Args:
            documents: [{"id": str, "text": str}, ...]
        """
        self.bm25.build(documents)
        bm25_path = self.config.get("bm25_index_path", "./data/bm25_index.json")
        self.bm25.save(bm25_path)
        self._bm25_loaded = True
        print(f"[OK] BM25 index built: {self.bm25.doc_count} docs, {self.bm25.term_count} terms")
    
    def search_with_threshold(self, query: str, top_k: int = 10, 
                              threshold: float = 0.5,
                              filters: Optional[Dict] = None) -> List[Dict]:
        """带相似度阈值的语义搜索"""
        results = self.search(query, top_k=top_k, filters=filters)
        filtered = [r for r in results if r["score"] >= threshold]
        return filtered
    
    def get(self, id: str) -> Optional[Dict]:
        """根据ID获取文档"""
        result = self.collection.get(ids=[id])
        if result and result["ids"]:
            return {
                "id": result["ids"][0],
                "document": result["documents"][0],
                "metadata": result["metadatas"][0] if result["metadatas"] else {}
            }
        return None
    
    def get_all(self) -> List[Dict]:
        """获取所有文档"""
        result = self.collection.get()
        if not result or not result["ids"]:
            return []
        
        formatted = []
        for i in range(len(result["ids"])):
            formatted.append({
                "id": result["ids"][i],
                "document": result["documents"][i] if result["documents"] else "",
                "metadata": result["metadatas"][i] if result["metadatas"] else {}
            })
        return formatted
    
    def delete(self, id: str):
        """删除文档"""
        self.collection.delete(ids=[id])
    
    def count(self) -> int:
        """获取文档数量"""
        return self.collection.count()
    
    def reset(self):
        """清空数据库（谨慎使用）"""
        self.client.delete_collection(self.collection_name)
        if self.use_external_embedding and self.embedding_func:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_func
            )
        else:
            self.collection = self.client.create_collection(name=self.collection_name)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "collection_name": self.collection_name,
            "document_count": self.count(),
            "persist_directory": self.persist_dir,
            "embedding_model": self.model_name if self.use_external_embedding else "ChromaDB默认",
            "device": self.device if self.use_external_embedding else "cpu",
            "use_external_embedding": self.use_external_embedding
        }
