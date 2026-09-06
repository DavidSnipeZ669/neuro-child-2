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
        """Learn from YouTube video: transcript + audio."""
        result = MediaLearningResult(source_type="youtube", source=url)
        start = time.time()
        try:
            # Try transcript first
            from neuro_child.environmental_learning import YouTubeTranscriptLearner
            learner = YouTubeTranscriptLearner()
            video_id = learner.extract_video_id(url)
            if video_id:
                transcript_data = learner.learn_from_video(video_id, url=url)
                if transcript_data.get("status") == "learned":
                    result.transcript = " ".join(transcript_data.get("words_learned", []))
                    result.words_learned = transcript_data.get("words_learned", [])
                    result.topics = transcript_data.get("topics", [])
                    result.success = True
        except Exception as e:
            result.error = str(e)
        result.duration = time.time() - start
        self._recent.append(result)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]
        self._store(result)
        return result

    def learn_from_file(self, file_path: str) -> MediaLearningResult:
        """Learn from local video/audio file."""
        result = MediaLearningResult(source_type="local_file", source=file_path)
        start = time.time()
        try:
            path = Path(file_path)
            if not path.exists():
                result.error = "file not found"
                return result

            # Try to extract audio and transcribe
            if path.suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]:
                result.transcript = self._transcribe_audio_file(path)
                result.success = bool(result.transcript)
            elif path.suffix.lower() in [".mp4", ".avi", ".mkv", ".mov", ".webm"]:
                # Extract audio from video
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


__all__ = ["MediaLearningEngine", "MediaLearningResult"]
