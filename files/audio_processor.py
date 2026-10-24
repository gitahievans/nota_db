import logging
from pathlib import Path
from typing import Callable

from django.conf import settings
from music21 import converter, stream

from .score_cleanup import normalize_score_stream

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, int | None], None]


def transcribe_audio_to_musicxml(
    score_id: int,
    input_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Path, dict]:
    """Run Basic Pitch on an audio file and materialize cleaned score artifacts."""
    if not input_path.exists():
        raise FileNotFoundError(f"Audio file not found at {input_path}")

    temp_dir = settings.TEMP_STORAGE_DIR / str(score_id)
    temp_dir.mkdir(parents=True, exist_ok=True)
    raw_midi_path = temp_dir / "preview.mid"
    output_xml_path = temp_dir / "output.xml"

    try:
        from basic_pitch.inference import predict
    except ImportError as exc:
        raise RuntimeError(
            "Basic Pitch is not installed in the backend worker environment."
        ) from exc

    if progress_callback:
        progress_callback("TRANSCRIBING_AUDIO", "Transcribing audio with Basic Pitch", 30)

    try:
        _, midi_data, _ = predict(str(input_path))
    except Exception as exc:
        logger.exception("Basic Pitch transcription failed for %s", input_path)
        raise RuntimeError(f"Audio transcription failed: {exc}") from exc

    if midi_data is None:
        raise RuntimeError("Basic Pitch did not return a MIDI transcription.")

    midi_data.write(str(raw_midi_path))
    logger.info("Saved raw Basic Pitch MIDI to %s", raw_midi_path)

    if progress_callback:
        progress_callback("CLEANING_TRANSCRIPTION", "Cleaning symbolic transcription", 50)

    try:
        raw_score_stream = converter.parse(raw_midi_path)
        if isinstance(raw_score_stream, stream.Opus):
            raw_score_stream = raw_score_stream.toScore()
        cleaned_score, metadata = normalize_score_stream(raw_score_stream, "audio")
    except Exception as exc:
        logger.exception("Failed to clean transcribed MIDI for %s", input_path)
        raise RuntimeError(f"Failed to clean transcribed MIDI: {exc}") from exc

    if progress_callback and metadata.get("used_piano_split"):
        progress_callback("SPLITTING_HANDS", "Splitting transcription into piano hands", 62)

    if progress_callback:
        progress_callback("GENERATING_MUSICXML", "Generating cleaner MusicXML draft", 75)

    try:
        cleaned_score.write("musicxml", fp=output_xml_path)
    except Exception as exc:
        logger.exception("Failed to write MusicXML for %s", input_path)
        raise RuntimeError(f"Failed to generate MusicXML from transcription: {exc}") from exc

    logger.info("Generated MusicXML at %s", output_xml_path)
    return output_xml_path, metadata
