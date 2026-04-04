#!/usr/bin/env python3
"""
Transcribe all Trend Following 5th Edition .m4b chapters using faster-whisper.
Creates one .txt file per chapter.

Model resolution (first match wins):
  1. WHISPER_MODEL_PATH — absolute path to a local faster-whisper model directory
  2. ~/.cache/huggingface_local/hub/models--Systran--faster-whisper-small.en/snapshots/<rev>/
  3. ~/.cache/huggingface/hub/models--Systran--faster-whisper-small.en/snapshots/<rev>/
  4. "small.en" (download via Hugging Face Hub)
"""

import os
from pathlib import Path

from faster_whisper import WhisperModel

# Systran faster-whisper-small.en layout under Hugging Face cache
_HF_SMALL_EN = "models--Systran--faster-whisper-small.en/snapshots"


def resolve_model_path() -> str:
    env = os.environ.get("WHISPER_MODEL_PATH", "").strip()
    if env and Path(env).is_dir():
        return env

    home = Path.home()
    for base in (
        home / ".cache/huggingface_local/hub",
        home / ".cache/huggingface/hub",
    ):
        snaps = base / _HF_SMALL_EN
        if not snaps.is_dir():
            continue
        candidates = sorted(p for p in snaps.iterdir() if p.is_dir())
        if candidates:
            return str(candidates[-1])

    return "small.en"


def main():
    audio_dir = Path("audio")
    model_name = resolve_model_path()
    
    # Find all chapter files
    pattern = "Trend Following, 5th Edition* - *.m4b"
    m4b_files = sorted(audio_dir.glob(pattern))
    
    if not m4b_files:
        print("❌ No matching .m4b files found!")
        print(f"Searched for: {pattern}")
        print("Files in audio/:")
        for f in sorted(audio_dir.iterdir()):
            if f.suffix.lower() in ('.m4b', '.m4a', '.mp3'):
                print("  ", f.name)
        return
    
    print(f"Found {len(m4b_files)} chapters to transcribe.\n")

    src = "local dir" if Path(model_name).is_dir() else "Hugging Face Hub"
    print(f"Loading Whisper ({src}): {model_name}")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    
    for i, m4b_path in enumerate(m4b_files, 1):
        txt_path = m4b_path.with_suffix(".txt")
        
        if txt_path.exists():
            print(f"[{i:2d}/{len(m4b_files)}] ✅ Already done: {txt_path.name}")
            continue
            
        print(f"[{i:2d}/{len(m4b_files)}] Transcribing: {m4b_path.name}")
        
        try:
            segments, info = model.transcribe(
                str(m4b_path),
                language="en",
                beam_size=5,
                vad_filter=True,
                word_timestamps=False,
                temperature=0.0,
            )
            
            text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip())
            
            txt_path.write_text(text + "\n", encoding="utf-8")
            print(f"   → Wrote {txt_path.name} ({len(text):,} characters)")
            
        except Exception as e:
            print(f"   ❌ Error on {m4b_path.name}: {e}")
    
    print("\n🎉 All transcriptions complete!")

if __name__ == "__main__":
    main()
