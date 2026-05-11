from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

import httpx

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None

try:
    import pvporcupine
except Exception:  # pragma: no cover - optional dependency
    pvporcupine = None

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - optional dependency
    WhisperModel = None

try:
    from pynput import keyboard
except Exception:  # pragma: no cover - optional dependency
    keyboard = None

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional dependency
    sd = None


class VoiceInterface:
    def __init__(
        self,
        daemon_url: str = "http://127.0.0.1:7799",
        wake_phrase: str = "Hey Focus",
        whisper_model: str = "base",
        piper_voice_path: Optional[str] = None,
    ) -> None:
        self.daemon_url = daemon_url
        self.wake_phrase = wake_phrase
        self.piper_voice_path = piper_voice_path
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._hotkey_pressed = threading.Event()

        self.model = WhisperModel(whisper_model, compute_type="int8") if WhisperModel else None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _listen_hotkey(self) -> None:
        if keyboard is None:
            return

        def on_press(key) -> None:
            combo = {keyboard.Key.ctrl_l, keyboard.Key.shift, keyboard.Key.space}
            if key in combo:
                self._hotkey_pressed.set()

        with keyboard.Listener(on_press=on_press) as listener:
            while not self._stop.is_set():
                pass
            listener.stop()

    def _run(self) -> None:
        if keyboard is not None:
            threading.Thread(target=self._listen_hotkey, daemon=True).start()

        while not self._stop.is_set():
            if self._hotkey_pressed.is_set():
                self._hotkey_pressed.clear()
                transcript = self.record_and_transcribe()
                if transcript:
                    reply = self.send_to_focus(transcript)
                    if reply:
                        self.speak(reply)

    def record_and_transcribe(self, seconds: float = 8.0, sample_rate: int = 16000) -> str:
        if sd is None or self.model is None or np is None:
            return ""

        audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
        sd.wait()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(np.asarray(audio).tobytes())

        segments, _ = self.model.transcribe(str(wav_path), vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        wav_path.unlink(missing_ok=True)
        return text

    def send_to_focus(self, message: str) -> str:
        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.post(f"{self.daemon_url}/chat", json={"message": message})
                res.raise_for_status()
                payload = res.json()
                return payload.get("reply", "")
        except Exception:
            return ""

    def speak(self, text: str) -> None:
        if not text.strip():
            return

        if self.piper_voice_path:
            cmd = ["piper", "--model", self.piper_voice_path]
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=False)
                return
            except FileNotFoundError:
                pass

        # Fallback: no-op when Piper is unavailable.
        _ = json.dumps({"tts_unavailable": True, "text": text})
