from __future__ import annotations

import asyncio
import tempfile
import threading
import time
from pathlib import Path


VOICE_OPTIONS = (
    "hi-IN-MadhurNeural",
    "hi-IN-SwaraNeural",
    "en-IN-PrabhatNeural",
    "en-IN-NeerjaNeural",
)


class VoiceSystem:
    def __init__(self) -> None:
        self._speech_lock = threading.Lock()

    def listen_continuously(
        self,
        on_text,
        stop_event: threading.Event,
        active_event: threading.Event,
        on_error,
    ) -> None:
        try:
            import speech_recognition as sr
        except ImportError as exc:
            raise RuntimeError("Install SpeechRecognition and PyAudio to use voice input.") from exc

        recognizer = sr.Recognizer()
        last_error = ""
        while not stop_event.is_set():
            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)
                    if last_error:
                        last_error = ""
                    while not stop_event.is_set():
                        if not active_event.wait(0.1):
                            continue
                        try:
                            audio = recognizer.listen(source, timeout=1, phrase_time_limit=15)
                        except sr.WaitTimeoutError:
                            continue
                        if stop_event.is_set() or not active_event.is_set():
                            continue
                        try:
                            text = self._recognize(recognizer, audio, sr)
                        except sr.UnknownValueError:
                            continue
                        except sr.RequestError as exc:
                            message = f"Speech recognition service unavailable: {exc}"
                            if message != last_error:
                                on_error(message)
                                last_error = message
                            stop_event.wait(3)
                            continue
                        if text and active_event.is_set() and not stop_event.is_set():
                            last_error = ""
                            on_text(text)
            except (OSError, AttributeError) as exc:
                message = (
                    "No usable microphone was found. Check that PyAudio is installed "
                    f"and the microphone is available: {exc}"
                )
                if message != last_error:
                    on_error(message)
                    last_error = message
                stop_event.wait(3)

    def listen(self) -> str:
        try:
            import speech_recognition as sr
        except ImportError as exc:
            raise RuntimeError("Install SpeechRecognition and PyAudio to use voice input.") from exc
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=20)
        except (OSError, AttributeError) as exc:
            raise RuntimeError("No usable microphone was found. Check that PyAudio is installed and the microphone is available.") from exc
        try:
            return self._recognize(recognizer, audio, sr)
        except sr.UnknownValueError as exc:
            raise RuntimeError("Speech could not be understood. Try speaking more clearly.") from exc
        except sr.RequestError as exc:
            raise RuntimeError(f"Speech recognition service unavailable: {exc}") from exc

    @staticmethod
    def _recognize(recognizer, audio, sr) -> str:
        for language in ("hi-IN", "en-US"):
            try:
                return recognizer.recognize_google(audio, language=language)
            except sr.UnknownValueError:
                continue
            except sr.RequestError:
                raise
        raise sr.UnknownValueError()

    def speak(self, text: str, voice: str = "hi-IN-MadhurNeural") -> None:
        try:
            import edge_tts
            import pygame
        except ImportError as exc:
            raise RuntimeError("Install edge-tts and pygame to use speech output.") from exc
        with self._speech_lock:
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as audio_file:
                    temporary_path = Path(audio_file.name)
                asyncio.run(edge_tts.Communicate(text[:6000], voice=voice).save(str(temporary_path)))
                pygame.mixer.init()
                pygame.mixer.music.load(str(temporary_path))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            finally:
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.quit()
                except pygame.error:
                    pass
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)


def normalize_voice_command(text: str) -> str:
    command = text.strip()
    lowered = command.casefold()
    if lowered.startswith("/"):
        return command
    if lowered.startswith(("code ", "write code ", "edit code ")):
        if lowered.startswith("write code "):
            return f"/code {command[11:].strip()}"
        if lowered.startswith("edit code "):
            return f"/code {command[10:].strip()}"
        return f"/code {command[5:].strip()}"
    if lowered.startswith("कोड "):
        return f"/code {command[4:].strip()}"
    if lowered in {"list files", "show files"}:
        return "/files"
    if lowered in {"list processes", "show processes"}:
        return "/processes"
    if lowered.startswith("open "):
        return f"/open {command[5:].strip()}"
    if lowered in {"take a screenshot", "show my screen"}:
        return "/screen"
    return command
