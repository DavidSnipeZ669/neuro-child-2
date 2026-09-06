"""
YouTube transcript extraction and learning.
Learns language, topics, and knowledge from YouTube videos.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-untyped]
    HAS_YOUTUBE_API = True
except ImportError:
    HAS_YOUTUBE_API = False

ROOT = Path(__file__).resolve().parent.parent
YOUTUBE_LEARNING_LOG = ROOT / "neuro_child" / "memory" / "youtube_learning.json"


@dataclass
class VideoKnowledge:
    video_id: str
    title: str = ""
    url: str = ""
    transcript: str = ""
    language: str = "en"
    words_learned: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    times_watched: int = 1
    chunks_learned: int = 0


class YouTubeTranscriptLearner:
    """
    Extracts transcripts from YouTube videos and learns from them.
    Supports: language learning, topic learning, vocabulary building.
    """

    def __init__(self) -> None:
        self.video_knowledge: Dict[str, VideoKnowledge] = {}
        self._load_history()

    def _load_history(self) -> None:
        if not YOUTUBE_LEARNING_LOG.exists():
            return
        try:
            data = json.loads(YOUTUBE_LEARNING_LOG.read_text(encoding="utf-8"))
            for item in data:
                vk = VideoKnowledge(**item)
                self.video_knowledge[vk.video_id] = vk
        except Exception:
            pass

    def save_history(self) -> None:
        data = [vk.__dict__ for vk in self.video_knowledge.values()]
        tmp = YOUTUBE_LEARNING_LOG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(YOUTUBE_LEARNING_LOG)

    def extract_video_id(self, url_or_id: str) -> Optional[str]:
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
            r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
            r"(?:embed\/)([0-9A-Za-z_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(1)
        if re.match(r"^[0-9A-Za-z_-]{11}$", url_or_id.strip()):
            return url_or_id.strip()
        return None

    def get_transcript(self, video_id: str, languages: Optional[List[str]] = None) -> Optional[str]:
        languages = languages or ["en", "en-US", "en-GB", "a.en"]
        if not HAS_YOUTUBE_API:
            return None
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            try:
                transcript = transcript_list.find_transcript(languages)
            except Exception:
                try:
                    transcript = transcript_list.find_generated_transcript(languages)
                except Exception:
                    try:
                        transcript = transcript_list.find_manually_created_transcript(languages)
                    except Exception:
                        return None
            segments = transcript.fetch()
            text = " ".join(segment.text for segment in segments)
            return text
        except Exception:
            return None

    def learn_from_video(self, video_id: str, title: str = "", url: str = "") -> Dict[str, Any]:
        existing = self.video_knowledge.get(video_id)
        if existing:
            existing.times_watched += 1
            existing.timestamp = time.time()
            self.save_history()
            return {
                "video_id": video_id,
                "status": "already_learned",
                "times_watched": existing.times_watched,
                "topics": existing.topics,
            }

        transcript = self.get_transcript(video_id)
        if not transcript:
            return {"video_id": video_id, "status": "no_transcript", "error": "Transcript unavailable or API not installed"}

        words = self._extract_learning_words(transcript)
        topics = self._detect_topics(transcript)

        vk = VideoKnowledge(
            video_id=video_id,
            title=title or f"YouTube Video {video_id}",
            url=url or f"https://youtu.be/{video_id}",
            transcript=transcript,
            words_learned=words,
            topics=topics,
            chunks_learned=len(transcript.split()) // 50,
        )
        self.video_knowledge[video_id] = vk
        self.save_history()
        return {
            "video_id": video_id,
            "status": "learned",
            "title": vk.title,
            "words_learned": words[:20],
            "topics": topics,
            "transcript_length": len(transcript),
            "chunks_learned": vk.chunks_learned,
        }

    def learn_from_url(self, url: str, title: str = "") -> Dict[str, Any]:
        video_id = self.extract_video_id(url)
        if not video_id:
            return {"status": "invalid_url", "url": url}
        return self.learn_from_video(video_id, title=title, url=url)

    def _extract_learning_words(self, text: str, max_words: int = 50) -> List[str]:
        stop_words = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "her", "was", "one", "our",
                      "out", "has", "have", "had", "this", "that", "with", "they", "from", "what", "when", "where",
                      "which", "their", "there", "would", "could", "should", "about", "been", "has", "have", "does",
                      "just", "know", "take", "into", "your", "my", "so", "no", "yes", "more", "some", "like", "them",
                      "come", "could", "would", "there", "their", "what", "which", "when", "make", "like", "time",
                      "just", "know", "take", "people", "into", "year", "your", "good", "some", "could", "them",
                      "other", "than", "then", "now", "look", "only", "come", "its", "over", "think", "also", "back",
                      "after", "use", "two", "how", "our", "work", "first", "well", "way", "even", "new", "want",
                      "because", "any", "these", "give", "day", "most"}
        words = re.findall(r"[a-zA-Z]+", text.lower())
        unique_words = []
        for w in words:
            if len(w) > 3 and w not in stop_words and w not in unique_words:
                unique_words.append(w)
        return unique_words[:max_words]

    def _detect_topics(self, text: str) -> List[str]:
        topic_keywords = {
            "gaming": ["game", "play", "player", "level", "score", "win", "lose", "character", "quest", "fps", "rpg"],
            "tech": ["computer", "software", "code", "programming", "app", "tech", "digital", "internet", "data"],
            "science": ["science", "experiment", "theory", "physics", "chemistry", "biology", "research"],
            "music": ["music", "song", "band", "guitar", "piano", "sing", "melody", "rhythm"],
            "cooking": ["recipe", "cook", "kitchen", "food", "ingredient", "bake", "meal", "dish"],
            "education": ["learn", "teach", "school", "university", "study", "lesson", "tutorial"],
            "comedy": ["funny", "joke", "laugh", "comedy", "hilarious", "meme", "skit"],
            "news": ["news", "report", "breaking", "politics", "world", "economy"],
            "sports": ["game", "team", "player", "score", "win", "championship", "league"],
            "lifestyle": ["life", "daily", "routine", "vlog", "morning", "night", "habits"],
        }
        text_lower = text.lower()
        detected = []
        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                detected.append(topic)
        return detected[:5]

    def get_knowledge_summary(self) -> Dict[str, Any]:
        total_videos = len(self.video_knowledge)
        total_words = sum(len(vk.words_learned) for vk in self.video_knowledge.values())
        all_topics: Dict[str, int] = {}
        for vk in self.video_knowledge.values():
            for t in vk.topics:
                all_topics[t] = all_topics.get(t, 0) + 1
        return {
            "total_videos_learned": total_videos,
            "total_unique_words": total_words,
            "topic_distribution": dict(sorted(all_topics.items(), key=lambda x: x[1], reverse=True)[:10]),
            "recent_videos": [{"id": vk.video_id, "title": vk.title, "topics": vk.topics}
                             for vk in sorted(self.video_knowledge.values(), key=lambda x: x.timestamp, reverse=True)[:5]],
        }


class ScreenContentAnalyzer:
    """
    Analyzes what's on screen and determines if it's learnable content.
    Detects: YouTube videos, games, educational content, coding, etc.
    """

    def __init__(self) -> None:
        self.content_history: List[Dict[str, Any]] = []
        self.last_content_type: str = "unknown"
        self.last_content_details: Dict[str, Any] = {}

    def analyze_screen_text(self, screen_text: str, window_title: str = "") -> Dict[str, Any]:
        lower = screen_text.lower()
        title_lower = window_title.lower()

        content_type = "unknown"
        confidence = 0.0
        learnable = False
        source = "unknown"

        # YouTube detection
        if "youtube.com" in lower or "youtu.be" in lower or "youtube" in title_lower:
            content_type = "youtube"
            confidence = 0.9
            learnable = True
            source = "YouTube"
            url_match = re.search(r"(https?://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]+)", screen_text)
            if url_match:
                self.last_content_details["url"] = url_match.group(1)

        # Gaming detection
        elif any(w in lower for w in ["steam", "epic games", "origin", "battle.net", "game", "playing", "fps", "rpg"]):
            content_type = "gaming"
            confidence = 0.8
            learnable = True
            source = "Game"
            if "steam" in lower:
                self.last_content_details["platform"] = "Steam"
            game_match = re.search(r"(?:Playing|Game|Running)[:\s]+([^\n]+)", screen_text, re.IGNORECASE)
            if game_match:
                self.last_content_details["game"] = game_match.group(1).strip()

        # Coding/Programming
        elif any(w in lower for w in ["visual studio", "vscode", "pycharm", "intellij", "terminal", "powershell", "bash", "python", "javascript", "code"]):
            content_type = "coding"
            confidence = 0.85
            learnable = True
            source = "IDE/Terminal"
            lang_match = re.search(r"(python|javascript|typescript|java|c\+\+|rust|go|ruby|php|html|css|sql)", lower)
            if lang_match:
                self.last_content_details["language"] = lang_match.group(1)

        # Educational content
        elif any(w in lower for w in ["coursera", "udemy", "khan academy", "edx", "tutorial", "learning", "course", "lesson"]):
            content_type = "education"
            confidence = 0.7
            learnable = True
            source = "Educational Platform"

        # Social media / browsing
        elif any(w in lower for w in ["reddit", "twitter", "x.com", "facebook", "instagram", "tiktok"]):
            content_type = "social_media"
            confidence = 0.6
            learnable = False
            source = "Social Media"

        # Video streaming
        elif any(w in lower for w in ["netflix", "disney+", "hulu", "amazon prime", "twitch", "streaming"]):
            content_type = "streaming"
            confidence = 0.7
            learnable = True
            source = "Streaming Service"
            if "twitch" in lower:
                source = "Twitch"

        result: Dict[str, Any] = {
            "content_type": content_type,
            "confidence": confidence,
            "learnable": learnable,
            "source": source,
            "timestamp": time.time(),
            "details": self.last_content_details,
        }

        if content_type != self.last_content_type:
            self.content_history.append(result)
            if len(self.content_history) > 100:
                self.content_history = self.content_history[-100:]
            self.last_content_type = content_type

        return result

    def get_recent_content(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.content_history[-limit:]
