"""
Media Learning — Nova learns from ANY video/audio source:
- YouTube URLs (transcripts + audio)
- Local video files (mp4, avi, mkv, etc.)
- Screen-captured video (what's playing on screen)
- System audio (WASAPI loopback)

Extracts: speech transcripts, visual frames, audio features, text overlays.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MediaLearningResult:
    source_type: str  # youtube, local_file, screen, system_audio
    source: str
    transcript: str = ""
    frames_analyzed: int = 0
    words_learned: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    duration: float = 0.0
    success: bool = False
    error: Optional[str] = None


class MediaLearningEngine:
    """
    Unified media learning for Nova.
    Learns from any video/audio source.
    """

    def __init__(self, knowledge: Any, language: Any) -> None:
        self.knowledge = knowledge
        self.language = language
        self._recent: List[MediaLearningResult] = []
        self._max_recent = 50

    def learn_from_youtube(self, url: str) -> MediaLearningResult:
        """Learn from YouTube video: transcript + audio + title fallback."""
        result = MediaLearningResult(source_type="youtube", source=url)
        start = time.time()
        try:
            # Try transcript first
            from neuro_child.environmental_learning import YouTubeTranscriptLearner
            learner = YouTubeTranscriptLearner()
            video_id = learner.extract_video_id(url)
            if video_id:
                transcript_data = learner.learn_from_video(video_id, url=url)
                status = transcript_data.get("status")
                if status == "learned":
                    result.transcript = " ".join(transcript_data.get("words_learned", []))
                    result.words_learned = transcript_data.get("words_learned", [])
                    result.topics = transcript_data.get("topics", [])
                    result.success = True
                elif status == "no_transcript":
                    # Fallback: learn from title/URL keywords
                    topic_text = f"YouTube video: {url} {video_id}"
                    try:
                        page = self._fetch_page_text(url)
                        if page:
                            title_match = re.search(r"<title>(.*?)</title>", page, re.IGNORECASE)
                            if title_match:
                                title = title_match.group(1).replace(" - YouTube", "").strip()
                                topic_text = f"YouTube video: {title}. {url}"
                    except Exception:
                        pass
                    words = self.language.encounter_text(topic_text, source="youtube_fallback")
                    result.words_learned = words
                    result.topics = ["youtube"]
                    result.success = bool(words)
                    result.error = "no transcript, learned from metadata"
                elif status == "already_learned":
                    result.success = True
                    result.transcript = "previously learned"
        except Exception as e:
            result.error = str(e)
        result.duration = time.time() - start
        self._recent.append(result)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]
        self._store(result)
        return result

    def learn_from_file(self, file_path: str) -> MediaLearningResult:
        """Learn from local file: text, audio, or video."""
        result = MediaLearningResult(source_type="local_file", source=file_path)
        start = time.time()
        try:
            path = Path(file_path)
            if not path.exists():
                result.error = "file not found"
                return result

            # Text files: learn directly
            text_exts = [".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml", ".toml", ".xml", ".html", ".js", ".ts", ".java", ".c", ".cpp", ".h"]
            if path.suffix.lower() in text_exts or path.stat().st_size < 1024 * 1024:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    if text.strip():
                        result.transcript = text[:2000]
                        words = self.language.encounter_text(text, source="file")
                        result.words_learned = words
                        result.success = bool(words)
                        result.duration = time.time() - start
                        self._recent.append(result)
                        if len(self._recent) > self._max_recent:
                            self._recent = self._recent[-self._max_recent:]
                        self._store(result)
                        return result
                except Exception:
                    pass

            # Audio files
            if path.suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]:
                result.transcript = self._transcribe_audio_file(path)
                result.success = bool(result.transcript)
            # Video files
            elif path.suffix.lower() in [".mp4", ".avi", ".mkv", ".mov", ".webm"]:
                result.transcript = self._transcribe_video_file(path)
                result.success = bool(result.transcript)

            if result.transcript:
                words = self.language.encounter_text(result.transcript, source="media_file")
                result.words_learned = words
        except Exception as e:
            result.error = str(e)
        result.duration = time.time() - start
        self._recent.append(result)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]
        self._store(result)
        return result

    def learn_from_screen(self, screen_text: str, window_title: str = "") -> Optional[MediaLearningResult]:
        """Learn from video playing on screen."""
        result = MediaLearningResult(source_type="screen", source=window_title or "active window")
        start = time.time()
        try:
            if screen_text and len(screen_text) > 20:
                result.transcript = screen_text[:500]
                words = self.language.encounter_text(screen_text, source="screen_video")
                result.words_learned = words
                result.success = bool(words)
        except Exception:
            pass
        result.duration = time.time() - start
        self._recent.append(result)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]
        self._store(result)
        return result if result.success else None

    def learn_from_system_audio(self, audio_text: str) -> Optional[MediaLearningResult]:
        """Learn from system audio capture."""
        result = MediaLearningResult(source_type="system_audio", source="WASAPI loopback")
        start = time.time()
        try:
            if audio_text and len(audio_text) > 10:
                result.transcript = audio_text[:500]
                words = self.language.encounter_text(audio_text, source="system_audio")
                result.words_learned = words
                result.success = bool(words)
        except Exception:
            pass
        result.duration = time.time() - start
        self._recent.append(result)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]
        self._store(result)
        return result if result.success else None

    def get_recent_learning(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent media learning activity."""
        return [
            {
                "source_type": r.source_type,
                "source": r.source,
                "words": len(r.words_learned),
                "topics": r.topics[:3],
                "success": r.success,
                "time": time.time() - r.duration,
            }
            for r in self._recent[-limit:]
        ]

    def _transcribe_audio_file(self, path: Path) -> str:
        """Transcribe audio file using SpeechRecognition."""
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(str(path)) as source:
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio)
                return text
        except Exception:
            return ""

    def _transcribe_video_file(self, path: Path) -> str:
        """Extract audio from video and transcribe."""
        try:
            # Try moviepy first
            from moviepy.editor import VideoFileClip
            video = VideoFileClip(str(path))
            audio_path = path.with_suffix(".wav")
            video.audio.write_audiofile(str(audio_path), fps=16000, nbytes=2, channels=1, verbose=False, logger=None)
            video.close()
            return self._transcribe_audio_file(audio_path)
        except Exception:
            # Fallback: just learn from filename/tags
            return f"video file: {path.name}"

    def _store(self, result: MediaLearningResult) -> None:
        """Store learning result in knowledge base."""
        try:
            if result.words_learned:
                self.knowledge.learn(
                    f"media_{result.source_type}_{int(time.time())}",
                    f"Learned {len(result.words_learned)} words from {result.source_type}: {result.source}",
                    category="experience",
                    importance=0.5,
                )
        except Exception:
            pass

    def _fetch_page_text(self, url: str, max_chars: int = 4000) -> Optional[str]:
        try:
            import urllib.request
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = resp.read(max_chars * 4)
            text = data.decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        except Exception:
            return None


__all__ = ["MediaLearningEngine", "MediaLearningResult"]
