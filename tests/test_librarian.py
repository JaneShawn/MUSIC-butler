"""
Librarian Agent 测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.librarian import LibrarianAgent, Song


def test_song_to_text():
    """测试Song转换为文本"""
    song = Song(
        id="test123",
        file_path="/music/test.mp3",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration=180.0,
        genre="Rock",
        year=2020,
        tags=["energetic", "guitar"]
    )
    
    text = song.to_text()
    
    assert "Test Song" in text
    assert "Test Artist" in text
    assert "Rock" in text
    assert "energetic" in text


def test_file_to_id():
    """测试文件ID生成"""
    agent = LibrarianAgent({
        "library": {"path": "./music", "supported_formats": [".mp3"]}
    })
    
    id1 = agent._file_to_id("/path/to/song.mp3")
    id2 = agent._file_to_id("/path/to/song.mp3")
    id3 = agent._file_to_id("/path/to/other.mp3")
    
    assert id1 == id2  # 相同路径生成相同ID
    assert id1 != id3  # 不同路径生成不同ID
    assert len(id1) == 16  # ID长度为16


def test_get_stats_empty():
    """测试空库统计"""
    agent = LibrarianAgent({
        "library": {"path": "./music", "supported_formats": [".mp3"]}
    })
    
    stats = agent.get_stats()
    
    assert stats["total_songs"] == 0
    assert stats["artists"] == 0
    assert stats["albums"] == 0
    assert stats["genres"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
