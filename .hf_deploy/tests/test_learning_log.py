"""Tests for learning log module."""
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning_log import LearningLog


def test_learning_log_append():
    """Test appending entries to learning log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_log.json"
        log = LearningLog(path=log_path)
        
        # Append an entry
        log.append({"prompt": "test", "response": "response", "task_type": "test"})
        
        # Check entry was added
        entries = log.latest(10)
        assert len(entries) == 1
        assert entries[0]["prompt"] == "test"
        assert entries[0]["response"] == "response"
        assert "timestamp" in entries[0]


def test_learning_log_search():
    """Test searching learning log entries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_log.json"
        log = LearningLog(path=log_path)
        
        # Add entries
        log.append({"prompt": "hello world", "response": "hi"})
        log.append({"prompt": "foo bar", "response": "baz"})
        log.append({"prompt": "hello again", "response": "hello"})
        
        # Search
        results = log.search("hello")
        assert len(results) == 2
        
        results = log.search("foo")
        assert len(results) == 1
        
        results = log.search("nonexistent")
        assert len(results) == 0


def test_learning_log_max_entries():
    """Test max entries limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_log.json"
        log = LearningLog(path=log_path, max_entries=5)
        
        # Add more than max entries
        for i in range(10):
            log.append({"prompt": f"test{i}", "response": f"resp{i}"})
        
        # Should only keep last 5
        entries = log.latest(10)
        assert len(entries) == 5
        # Most recent should be last
        assert entries[0]["prompt"] == "test9"


def test_learning_log_persistence():
    """Test that log persists to file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_log.json"
        
        # Create and add entries
        log1 = LearningLog(path=log_path)
        log1.append({"prompt": "persist", "response": "test"})
        
        # Load from file
        log2 = LearningLog(path=log_path)
        entries = log2.latest(10)
        assert len(entries) == 1
        assert entries[0]["prompt"] == "persist"


def test_learning_log_summary():
    """Test summary generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_log.json"
        log = LearningLog(path=log_path)
        
        # Add entries
        log.append({"prompt": "test1", "response": "resp1", "task_type": "type1", "model": "model1"})
        log.append({"prompt": "test2", "response": "resp2", "task_type": "type1", "model": "model2"})
        
        summary = log.summary()
        assert summary["entries"] == 2
        assert "last_entry" in summary


if __name__ == "__main__":
    test_learning_log_append()
    test_learning_log_search()
    test_learning_log_max_entries()
    test_learning_log_persistence()
    test_learning_log_summary()
    print("All learning log tests passed!")
