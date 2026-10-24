"""Regression checks for recognizer exit-zero failures and expiring diagnostics."""
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.utils import timezone
from datetime import timedelta
from files.audiveris_processor import process_with_audiveris, RecognitionError, DIAGNOSTIC_BYTES
from files.tasks import process_score
from files.lifecycle import cleanup_session
from files.outcomes import RECOGNITION_FAILURE_MESSAGE
from .orchestration import IsolatedScoreCase


class RecognitionFailureTests(IsolatedScoreCase):
    def run_recognizer(self, stdout='', stderr='', export=False, failure=None):
        def run(command, **kwargs):
            arguments = next(arg for arg in command if arg.startswith('-PcmdLineArgs=')).split(',')
            workspace = Path(arguments[arguments.index('-output') + 1])
            (workspace / 'audiveris.log').write_text('private recognition details')
            if failure:
                raise failure
            if export:
                with zipfile.ZipFile(workspace / 'input.mxl', 'w') as archive:
                    archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>')
                    archive.writestr('score.xml', self.recognized.read_bytes())
            return subprocess.CompletedProcess(command, 0, stdout, stderr)
        with patch('files.audiveris_processor.AUDIVERIS_HOME', str(self.root)), patch('files.audiveris_processor.subprocess.run', side_effect=run):
            return process_with_audiveris(self.score.pk, 'pdf', self.root / str(self.score.pk) / 'input.pdf')

    def test_exit_zero_without_export_is_failure_and_retains_private_logs(self):
        directory = self.prepare_score()
        with self.assertRaises(RecognitionError) as caught:
            self.run_recognizer(stdout='No export\n/private/internal\n', stderr='warning')
        self.assertEqual(caught.exception.code, 'recognition_no_output')
        self.assertNotIn('/private', str(caught.exception))
        self.assertEqual(str(caught.exception), RECOGNITION_FAILURE_MESSAGE)
        logs = list((directory / 'diagnostics' / 'recognition').glob('*.log'))
        self.assertEqual(len(logs), 3)
        self.assertIn('/private/internal', ''.join(p.read_text() for p in logs))
        self.assertEqual(list(directory.glob('audiveris_*')), [])
        self.assertFalse((directory / 'output.xml').exists())

    def test_barline_engine_exception_has_allowlisted_cause(self):
        self.prepare_score()
        with self.assertRaises(RecognitionError) as caught:
            self.run_recognizer(stdout='java.lang.IllegalStateException: No abscissa computable for StaffBarlineInter#10258\n at /private/server')
        self.assertEqual(caught.exception.code, 'recognition_barline_error')
        self.assertEqual(str(caught.exception), RECOGNITION_FAILURE_MESSAGE)
        self.assertNotIn('10258', str(caught.exception))
        self.assertNotIn('/private', str(caught.exception))

    def test_incomplete_transcription_is_not_mislabelled_low_quality(self):
        self.prepare_score()
        with self.assertRaises(RecognitionError) as caught:
            self.run_recognizer(stdout='Could not export since transcription did not complete successfully')
        self.assertEqual(caught.exception.code, 'recognition_incomplete')

    def test_failed_diagnostic_logs_are_bounded_and_deleted_with_session(self):
        directory = self.prepare_score()
        self.score.retention_kind = 'analysis'
        self.score.save(update_fields=['retention_kind'])
        with self.assertRaises(RecognitionError):
            self.run_recognizer(stdout='x' * (DIAGNOSTIC_BYTES * 2))
        logs = list((directory / 'diagnostics' / 'recognition').glob('*.log'))
        self.assertLessEqual(sum(p.stat().st_size for p in logs), 4 * DIAGNOSTIC_BYTES)
        self.score.job_state = 'FAILURE'
        self.score.expires_at = timezone.now() - timedelta(seconds=1)
        self.score.save()
        self.assertEqual(cleanup_session(self.score.pk), 'deleted')
        self.assertFalse(directory.exists())

    def test_timeout_logs_survive_workspace_removal(self):
        directory = self.prepare_score()
        with self.assertRaisesRegex(Exception, 'timed out'):
            self.run_recognizer(failure=subprocess.TimeoutExpired('audiveris', 600, output=b'last step RHYTHMS', stderr=b'private error'))
        texts = ''.join(p.read_text() for p in (directory / 'diagnostics' / 'recognition').glob('*.log'))
        self.assertIn('last step RHYTHMS', texts)
        self.assertEqual(list(directory.glob('audiveris_*')), [])

    def test_success_retains_canonical_notation_without_diagnostic_archive(self):
        directory = self.prepare_score()
        mxl, xml = self.run_recognizer(stdout='warnings do not imply failure', export=True)
        self.assertEqual(Path(xml).read_bytes(), self.recognized.read_bytes())
        self.assertTrue(Path(mxl).exists())
        self.assertFalse((directory / 'diagnostics').exists())

    def test_recognition_failure_cause_is_pollable_without_exposing_private_details(self):
        self.prepare_score()
        failure = RecognitionError('recognition_barline_error', RECOGNITION_FAILURE_MESSAGE)
        with patch('files.tasks.process_with_audiveris', side_effect=failure), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async'):
            with self.assertRaises(RecognitionError):
                process_score.run(self.score.pk, 'pdf', 'pdf')
        response = self.client.get(f'/api/scores/{self.score.pk}/')
        self.assertEqual(response.status_code, 200)
        task = response.data['task_status']
        self.assertEqual(task['state'], 'FAILURE')
        self.assertEqual(task['info']['stage'], 'FAILED')
        self.assertEqual(task['info']['failure_stage'], 'GENERATING_MUSICXML')
        self.assertEqual(task['info']['code'], 'recognition_barline_error')
        self.assertEqual(task['info']['message'], RECOGNITION_FAILURE_MESSAGE)
        self.assertNotIn(str(self.root), str(response.data))

    def test_existing_generic_recognition_failure_uses_approved_feedback(self):
        self.prepare_score()
        self.score.job_state = 'FAILURE'
        self.score.job_stage = 'FAILED'
        self.score.results = {'processing': {'components': {'recognition': {
            'status': 'failed', 'stage': 'GENERATING_MUSICXML', 'code': 'recognition_failed',
            'message': 'Input could not be converted to notation.'}}}}
        self.score.save()
        response = self.client.get(f'/api/scores/{self.score.pk}/')
        self.assertEqual(response.data['task_status']['info']['message'], RECOGNITION_FAILURE_MESSAGE)
        self.assertEqual(response.data['task_status']['info']['code'], 'recognition_failed')
        self.score.source_type = 'audio'; self.score.save(update_fields=['source_type'])
        response = self.client.get(f'/api/scores/{self.score.pk}/')
        self.assertEqual(response.data['task_status']['info']['message'], 'Input could not be converted to notation.')

    def test_log_retention_failure_does_not_replace_processing_error(self):
        self.prepare_score()
        from files.audiveris_processor import temp_workspace
        with patch('files.audiveris_processor.Path.mkdir', side_effect=[None, OSError('diagnostics disk full')]):
            with self.assertRaisesRegex(ValueError, 'original recognition error'):
                with temp_workspace(str(self.score.pk)):
                    raise ValueError('original recognition error')
