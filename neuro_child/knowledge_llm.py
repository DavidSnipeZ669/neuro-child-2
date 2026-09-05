"""
NovaKnowledgeLLM — LLM 2: everything Nova has learned.
This is a lightweight embedding-free memory model that stores learned facts,
lessons, vocabulary, experiences, and relationships, then retrieves the
most relevant context for replies.

It is NOT a large language model. It is Nova's long-term memory + knowledge
graph, built from scratch to avoid third-party APIs.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MemoryNode:
    topic: str
    content: str
    category: str = "fact"  # fact, lesson, preference, vocabulary, experience
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)
    source: str = "user"
    timestamp: float = field(default_factory=__import__("time").time)
    access_count: int = 0
    last_access: float = field(default_factory=__import__("time").time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "content": self.content,
            "category": self.category,
            "importance": self.importance,
            "tags": self.tags,
            "source": self.source,
            "timestamp": self.timestamp,
            "access_count": self.access_count,
            "last_access": self.last_access,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryNode":
        return cls(**data)


class NovaKnowledgeLLM:
    """
    Stores all learned knowledge as a searchable index.
    Supports semantic-ish retrieval via term overlap + recency + importance.
    No external dependencies. Built for offline operation.
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path or Path(__file__).resolve().parent / "memory" / "knowledge.json"
        self.nodes: List[MemoryNode] = []
        self._stop_words = set(
            "a an the and or but if in on at to for with by from of is it was are be been have has "
            "i you he she we they me him her us them my your his its our their this that these those "
            "not no yes do did does can could would should will shall may might must".split()
        )
        self._load()

    # ---------- Storage ----------

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                self.nodes = [MemoryNode.from_dict(x) for x in data.get("nodes", [])]
            except Exception:
                self.nodes = []

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nodes": [n.to_dict() for n in self.nodes],
            "meta": {
                "total_nodes": len(self.nodes),
                "categories": {},
                "last_saved": __import__("time").time(),
            },
        }
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- Learning ----------

    def learn(self, topic: str, content: str, category: str = "fact", importance: float = 0.5, source: str = "user", tags: Optional[List[str]] = None) -> MemoryNode:
        """Store a new piece of knowledge."""
        node = MemoryNode(
            topic=topic.strip().lower(),
            content=content.strip(),
            category=category,
            importance=importance,
            source=source,
            tags=tags or self._extract_tags(content),
        )
        # Merge with existing if very similar topic exists
        existing = self._find_similar(topic)
        if existing:
            existing.content = content
            existing.importance = max(existing.importance, importance)
            existing.tags = list(set(existing.tags + node.tags))
            existing.last_access = __import__("time").time
            existing.access_count += 1
            return existing
        self.nodes.append(node)
        self.save()
        return node

    def reinforce(self, topic: str, amount: float = 0.1) -> None:
        """Increase importance of an existing topic."""
        for n in self.nodes:
            if n.topic == topic.strip().lower():
                n.importance = min(1.0, n.importance + amount)
                n.last_access = __import__("time").time
                n.access_count += 1
                self.save()
                return

    def forget(self, topic: str) -> bool:
        """Remove a topic."""
        before = len(self.nodes)
        self.nodes = [n for n in self.nodes if n.topic != topic.strip().lower()]
        if len(self.nodes) < before:
            self.save()
            return True
        return False

    # ---------- Retrieval ----------

    def query(self, text: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve the most relevant nodes for a query."""
        query_terms = self._tokenize(text)
        if not query_terms:
            return []

        scored: List[Tuple[float, MemoryNode]] = []
        nodes = [n for n in self.nodes if category is None or n.category == category]
        for n in nodes:
            score = self._score(n, query_terms)
            if score > 0:
                scored.append((score, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"score": s, "node": n.to_dict()} for s, n in scored[:top_k]]

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Most recently accessed memories."""
        nodes = sorted(self.nodes, key=lambda n: n.last_access, reverse=True)[:limit]
        return [n.to_dict() for n in nodes]

    def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        """All memories in a category."""
        return [n.to_dict() for n in self.nodes if n.category == category]

    def get_stats(self) -> Dict[str, Any]:
        """Memory statistics."""
        cats: Dict[str, int] = {}
        for n in self.nodes:
            cats[n.category] = cats.get(n.category, 0) + 1
        return {
            "total_memories": len(self.nodes),
            "categories": cats,
            "avg_importance": round(sum(n.importance for n in self.nodes) / max(len(self.nodes), 1), 3),
            "top_topics": [n.topic for n in sorted(self.nodes, key=lambda x: x.importance, reverse=True)[:20]],
        }

    # ---------- Generation Helper ----------

    def build_context(self, query_text: str, max_tokens: int = 200) -> str:
        """Build a context string from relevant memories for reply generation."""
        results = self.query(query_text, top_k=5)
        parts = []
        total = 0
        for r in results:
            node = r["node"]
            text = f"{node['topic']}: {node['content']}"
            if total + len(text) > max_tokens:
                break
            parts.append(text)
            total += len(text)
        return "\n".join(parts)

    def generate_reply_enhancement(self, user_text: str, base_reply: str) -> str:
        """Enhance a base reply with relevant memories."""
        context = self.build_context(user_text, max_tokens=150)
        if not context:
            return base_reply
        # Very lightweight enhancement: prepend relevant context if strongly related
        results = self.query(user_text, top_k=1)
        if results and results[0]["score"] > 0.6:
            top = results[0]["node"]
            enhancement = f"(from what I know: {top['content']})"
            if len(base_reply) + len(enhancement) < 300:
                return f"{base_reply} {enhancement}"
        return base_reply

    # ---------- Internals ----------

    def _extract_tags(self, text: str) -> List[str]:
        words = self._tokenize(text)
        return list({w for w in words if len(w) > 3})[:10]

    def _tokenize(self, text: str) -> List[str]:
        return [w.lower() for w in re.findall(r"[a-z']+", text.lower()) if w not in self._stop_words and len(w) > 2]

    def _find_similar(self, topic: str) -> Optional[MemoryNode]:
        topic_words = set(self._tokenize(topic))
        if not topic_words:
            return None
        best, best_score = None, 0.0
        for n in self.nodes:
            if n.category == "preference" and n.topic == topic:
                return n
            n_words = set(self._tokenize(n.topic))
            if not n_words:
                continue
            overlap = len(topic_words & n_words)
            score = overlap / max(len(topic_words | n_words), 1)
            if score > best_score and score > 0.6:
                best_score = score
                best = n
        return best

    def _score(self, node: MemoryNode, query_terms: List[str]) -> float:
        node_words = set(self._tokenize(node.topic + " " + node.content))
        if not node_words:
            return 0.0
        overlap = len(set(query_terms) & node_words)
        coverage = overlap / max(len(query_terms), 1)
        recency = math.exp(-(__import__("time").time() - node.last_access) / 86400)
        return coverage * 0.7 + node.importance * 0.2 + recency * 0.1


__all__ = ["NovaKnowledgeLLM", "MemoryNode"]
