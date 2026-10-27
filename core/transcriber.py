"""Vosk audio transcription engine."""

import json
import os
import wave
from pathlib import Path
from typing import Optional
from vosk import KaldiRecognizer, Model, SetLogLevel

from core.model_resolver import get_audio_dir, resolve_model_path

# Silence Kaldi debug logs (-1)
SetLogLevel(-1)


class VoskAudioTranscriber:
    """Wrapper around Vosk Kaldi speech recognizer for WAV files."""

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = resolve_model_path(model_path)
        print(f"[VOSK] Loading model from: {self.model_path}")
        self.model = Model(self.model_path)

    def transcribe_file(self, audio_path: str) -> str:
        """Transcribe a WAV file into text.

        Args:
            audio_path: Path to the WAV audio file.

        Returns:
            str: Transcribed text string.

        Raises:
            FileNotFoundError: If the audio file does not exist.
            ValueError: If audio is not mono 16-bit PCM.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        wf = wave.open(audio_path, "rb")
        try:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()

            if channels != 1:
                raise ValueError(f"Expected Mono (1 channel), got {channels}")
            if sample_width != 2:
                raise ValueError(f"Expected 16-bit PCM (2 bytes), got {sample_width}")

            recognizer = KaldiRecognizer(self.model, sample_rate)
            segments = []
            chunk = 4000

            while True:
                data = wf.readframes(chunk)
                if len(data) == 0:
                    break
                if recognizer.AcceptWaveform(data):
                    res = json.loads(recognizer.Result())
                    text = res.get("text", "").strip()
                    if text:
                        segments.append(text)

            final_res = json.loads(recognizer.FinalResult())
            trailing_text = final_res.get("text", "").strip()
            if trailing_text:
                segments.append(trailing_text)

            return " ".join(segments).strip()
        finally:
            wf.close()

    def get_audio_files(self, folder_path: Optional[str] = None) -> list[str]:
        """Find and return all .wav files in the folder."""
        folder = get_audio_dir(folder_path)
        if not folder.is_dir():
            raise FileNotFoundError(f"Audio folder not found: {folder}")
        return [str(p) for p in sorted(folder.glob("*.wav"))]