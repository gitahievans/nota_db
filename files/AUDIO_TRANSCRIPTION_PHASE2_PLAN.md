# Audio Transcription Phase 2

## Goal
Improve audio uploads from "analysis-first transcription" to "cleaner draft notation plus clearer playback".

## Backend priorities
- Clean symbolic transcription before MusicXML export.
- Split piano-like material into left and right hand staves.
- Keep a separate preview MIDI closer to the raw transcription.
- Preserve current analysis accuracy for key, meter, and structure.

## Frontend priorities
- Show original uploaded audio beside synthesized playback.
- Label audio notation as a transcribed draft, not polished sheet music.
- Use playback-specific MIDI for audio uploads when available.

## Success criteria
- Audio-generated notation is visibly less cluttered.
- Piano uploads often render on two staves.
- Users can compare original audio and generated playback.
- Analysis quality remains at least as good as Phase 1.
