from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch, Mock

from django.test import TestCase, override_settings
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from files.models import PDFFile
from files.tasks import process_score
from .references import FIXTURES, REFERENCES, fixture_hashes


class IsolatedScoreCase(TestCase):
    def setUp(self):
        self.originals = fixture_hashes()
        self.folder = tempfile.TemporaryDirectory(prefix="nota-case-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.settings_override = override_settings(TEMP_STORAGE_DIR=self.root, MEDIA_ROOT=self.root / "catalog")
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        field = PDFFile._meta.get_field("file")
        storage_patch = patch.object(field, "storage", FileSystemStorage(location=self.root / "catalog"))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.client = APIClient()
        self.addCleanup(self.assert_originals_unchanged)

    def assert_originals_unchanged(self):
        self.assertEqual(fixture_hashes(), self.originals)

    def prepare_score(self, reference="melody", source_type="pdf"):
        self.score = PDFFile.objects.create(title="Local verification", source_type=source_type)
        directory = self.root / str(self.score.id)
        directory.mkdir()
        shutil.copyfile(FIXTURES / "01-simple-melody.pdf", directory / "input.pdf")
        self.recognized = directory / "recognized.musicxml"
        shutil.copyfile(REFERENCES / f"{reference}.musicxml", self.recognized)
        return directory

    def run_pdf(self):
        # Real task, canonical XML boundary, analyzer and MIDI exporter; controlled OMR/broker only.
        with patch("files.tasks.process_with_audiveris", return_value=(str(self.recognized), {})) as omr, \
             patch.object(process_score, "update_state") as state, \
             patch("files.tasks.cleanup_temp_files.apply_async") as cleanup:
            result = process_score.run(self.score.id, "pdf", "pdf")
        self.score.refresh_from_db()
        return result, omr, state, cleanup


class OrchestrationTests(IsolatedScoreCase):
    def test_pdf_upload_dispatch_and_isolated_copy(self):
        original = (FIXTURES / "01-simple-melody.pdf").read_bytes()
        with patch("files.views.TextExtractor") as text, patch("files.views.process_score.delay", return_value=Mock(id="local-job")) as dispatch:
            text.return_value.extract_from_file.return_value = {"text": "controlled OCR"}
            response = self.client.post("/api/upload/", {
                "title": "Fixture", "analyze": "true",
                "file": SimpleUploadedFile("score.pdf", original, content_type="application/pdf"),
            }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        score = PDFFile.objects.get(pk=response.data["score_id"])
        self.assertFalse(score.file)
        self.assertEqual(response.data["task_id"], "local-job")
        dispatch.assert_called_once_with(score.id, file_ext="pdf", source_type="pdf")
        self.assertEqual((self.root / str(score.id) / "input.pdf").read_bytes(), original)

    def test_controlled_pipeline_detail_and_artifacts(self):
        directory = self.prepare_score()
        result, omr, state, cleanup = self.run_pdf()
        self.assertEqual(result["stage"], "COMPLETED")
        self.assertTrue(self.score.processed)
        self.assertTrue((directory / "output.xml").exists())
        self.assertTrue((directory / f"{self.score.id}.mid").read_bytes().startswith(b"MThd"))
        omr.assert_called_once_with(self.score.id, "pdf", directory / "input.pdf")
        cleanup.assert_called_once_with((self.score.id,), countdown=3600)
        detail = self.client.get(f"/api/scores/{self.score.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.data["score"]["processed"])
        for url in (self.score.musicxml_url, self.score.midi_url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(b"".join(response.streaming_content))
            response.close()

    def test_recognition_exception_has_stage_and_schedules_cleanup(self):
        self.prepare_score()
        with patch("files.tasks.process_with_audiveris", side_effect=RuntimeError("controlled recognizer failure")), \
             patch.object(process_score, "update_state"), patch("files.tasks.cleanup_temp_files.apply_async") as cleanup:
            with self.assertRaisesRegex(RuntimeError, "controlled recognizer failure"):
                process_score.run(self.score.id, "pdf", "pdf")
        self.score.refresh_from_db()
        self.assertFalse(self.score.processed)
        self.assertEqual(self.score.results["stage"], "GENERATING_MUSICXML")
        cleanup.assert_called_once()

    def test_missing_artifacts_are_404(self):
        self.prepare_score()
        for role in ("musicxml", "midi"):
            self.assertEqual(self.client.get(f"/api/serve-{role}/{self.score.id}/").status_code, 404)

    def test_catalog_upload_and_list_use_local_storage_and_no_task(self):
        with patch("files.views.process_score.delay") as dispatch:
            response = self.client.post("/api/upload/", {
                "title": "Catalog sample", "analyze": "false",
                "file": SimpleUploadedFile("catalog.pdf", b"%PDF-1.4 local catalog", content_type="application/pdf"),
            }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        dispatch.assert_not_called()
        score = PDFFile.objects.get(pk=response.data["score_id"])
        self.assertTrue(Path(score.file.path).is_relative_to(self.root))
        self.assertEqual(self.client.get("/api/files/").status_code, 200)

    def test_legacy_results_dictionary_and_json_string(self):
        from files.serializers import FileSerializer
        score = PDFFile.objects.create(title="Legacy", results={"parts": ["Flute"]})
        self.assertEqual(FileSerializer(score).data["results"], {"parts": ["Flute"]})
        score.results = '{"parts": ["Flute"]}'
        self.assertEqual(FileSerializer(score).data["results"], {"parts": ["Flute"]})

    def test_audio_upload_dispatches_without_ocr(self):
        with patch("files.views.TextExtractor") as text, patch("files.views.process_score.delay", return_value=Mock(id="audio-job")) as dispatch:
            response = self.client.post("/api/upload/", {
                "title": "Controlled audio", "analyze": "true",
                "file": SimpleUploadedFile("short.wav", b"controlled audio bytes", content_type="audio/wav"),
            }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        text.assert_not_called()
        dispatch.assert_called_once_with(response.data["score_id"], file_ext="wav", source_type="audio")

    def test_image_upload_uses_controlled_preprocessing_and_dispatch(self):
        with patch("files.views.FileUploadView.preprocess_image_for_audiveris", return_value=(True, "controlled")) as preprocess, \
             patch("files.views.TextExtractor") as text, patch("files.views.process_score.delay", return_value=Mock(id="image-job")) as dispatch:
            text.return_value.extract_from_file.return_value = {"text": "controlled OCR"}
            response = self.client.post("/api/upload/", {
                "title": "Controlled image", "analyze": "true",
                "file": SimpleUploadedFile("score.png", b"controlled image bytes", content_type="image/png"),
            }, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        preprocess.assert_called_once()
        dispatch.assert_called_once_with(response.data["score_id"], file_ext="png", source_type="image")

    def test_audio_task_uses_separate_controlled_transcription(self):
        directory = self.prepare_score(source_type="audio")
        (directory / "input.wav").write_bytes(b"controlled audio")
        shutil.copyfile(self.recognized, directory / "output.xml")
        with patch("files.tasks.transcribe_audio_to_musicxml", return_value=(directory / "output.xml", {"approximate": True})) as audio, \
             patch("files.tasks.process_with_audiveris") as omr, patch.object(process_score, "update_state"), \
             patch("files.tasks.cleanup_temp_files.apply_async"):
            result = process_score.run(self.score.id, "wav", "audio")
        self.score.refresh_from_db()
        self.assertEqual(result["stage"], "COMPLETED")
        self.assertEqual(self.score.results["audio_transcription"], {"approximate": True})
        audio.assert_called_once()
        omr.assert_not_called()
