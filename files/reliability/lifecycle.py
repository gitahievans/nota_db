"""P6 retention checks use owned copies, never catalog/fixture deletion by pattern."""
from datetime import timedelta
from io import StringIO
import shutil
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from files.models import PDFFile, Category
from files.tasks import process_score, cleanup_temp_files
from files.lifecycle import cleanup_session, recover_sessions, session_lock, lifetime, SessionBusy
from files.jobs import fail_job
from .orchestration import IsolatedScoreCase


class LifecycleTests(IsolatedScoreCase):
    def owned(self, terminal=False):
        directory = self.prepare_score()
        self.score.retention_kind = 'analysis'
        self.score.job_state = 'QUEUED'
        self.score.job_stage = 'QUEUED'
        self.score.job_updated_at = timezone.now()
        self.score.save()
        if terminal:
            self.run_pdf()
        return directory

    def expire(self):
        self.score.expires_at = timezone.now() - timedelta(seconds=1)
        self.score.save(update_fields=['expires_at'])

    def upload(self, **kwargs):
        return self.client.post('/api/upload/', {'title': 'temporary', 'analyze': 'true',
            'file': SimpleUploadedFile('a.pdf', b'%PDF', content_type='application/pdf'), **kwargs}, format='multipart')

    def test_terminal_time_is_one_hour_not_upload_time(self):
        self.owned()
        old = timezone.now() - timedelta(days=2)
        PDFFile.objects.filter(pk=self.score.pk).update(uploaded_at=old)
        before = timezone.now()
        self.run_pdf()
        self.assertGreaterEqual(self.score.terminal_at, before)
        self.assertEqual(self.score.expires_at - self.score.terminal_at, timedelta(hours=1))
        self.assertEqual(lifetime(self.score)['state'], 'available')
        self.assertEqual(cleanup_session(self.score.pk), 'not_due')
        response = self.client.get(f'/api/scores/{self.score.pk}/')
        self.assertEqual(response.data['score']['lifetime']['expires_at'], self.score.expires_at.isoformat())
        self.assertEqual(response['Cache-Control'], 'no-store')
        xml = self.client.get(self.score.musicxml_url)
        self.assertEqual(xml['Cache-Control'], 'no-store')
        xml.close()

    def test_failed_recognition_has_the_same_retention(self):
        self.owned()
        with patch('files.tasks.process_with_audiveris', side_effect=ValueError('recognition')), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async'):
            with self.assertRaises(ValueError):
                process_score.run(self.score.pk, 'pdf', 'pdf')
        self.score.refresh_from_db()
        self.assertEqual(self.score.job_state, 'FAILURE')
        self.assertEqual(self.score.expires_at - self.score.terminal_at, timedelta(hours=1))

    def test_analysis_upload_owns_session_and_exposes_pending_lifetime(self):
        with patch('files.views.TextExtractor') as text, patch('files.views.process_score.delay', return_value=Mock(id='job')):
            text.return_value.extract_from_file.return_value = {}
            response = self.upload(retention_kind='catalog', expires_at='2099-01-01')
        self.assertEqual(response.status_code, 201)
        score = PDFFile.objects.get(pk=response.data['score_id'])
        self.assertEqual(score.retention_kind, 'analysis')
        self.assertEqual(response.data['lifetime']['state'], 'processing')
        self.assertIsNone(response.data['lifetime']['expires_at'])

    def test_dispatch_failure_recovers_without_scheduled_task(self):
        with patch('files.views.TextExtractor') as text, patch('files.views.process_score.delay', side_effect=RuntimeError('offline')):
            text.return_value.extract_from_file.return_value = {}
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.score = PDFFile.objects.get(pk=response.data['score_id'])
        self.assertIsNotNone(self.score.expires_at)
        self.expire()
        recover_sessions()
        self.assertFalse(PDFFile.objects.filter(pk=self.score.pk).exists())

    def test_preprocessing_failure_gets_deadline_and_deletion(self):
        with patch('files.views.FileUploadView.preprocess_image_for_audiveris', return_value=(False, 'failure')):
            response = self.client.post('/api/upload/', {'title': 'bad', 'analyze': 'true',
                'file': SimpleUploadedFile('a.png', b'bad', content_type='image/png')}, format='multipart')
        self.score = PDFFile.objects.get(pk=response.data['score_id'])
        self.assertIsNotNone(self.score.expires_at)
        self.expire()
        self.assertEqual(cleanup_session(self.score.pk), 'deleted')

    def test_complete_directory_record_and_relationship_deletion_preserves_categories(self):
        directory = self.owned(terminal=True)
        category = Category.objects.create(name='Shared')
        self.score.categories.add(category)
        for name in ['preview.mid', 'basic_pitch_raw.mid', 'output.mxl', 'text_results.json', 'input.wav']:
            (directory / name).write_bytes(b'session-owned')
        workspace = directory / 'audiveris_interrupted'
        workspace.mkdir(); (workspace / 'recognition.omr').write_bytes(b'work')
        self.expire()
        self.assertEqual(cleanup_temp_files.run(self.score.pk), 'deleted')
        self.assertFalse(directory.exists())
        self.assertFalse(PDFFile.objects.filter(pk=self.score.pk).exists())
        self.assertFalse(PDFFile.categories.through.objects.filter(pdffile_id=self.score.pk).exists())
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())
        self.assertEqual(cleanup_temp_files.run(self.score.pk), 'excluded_or_missing')

    def test_missing_directory_does_not_prevent_row_deletion(self):
        directory = self.owned(terminal=True)
        shutil.rmtree(directory)
        self.expire()
        self.assertEqual(cleanup_session(self.score.pk), 'deleted')

    def test_partial_file_deletion_keeps_retry_intent_and_converges(self):
        directory = self.owned(terminal=True)
        self.expire()
        def partial(path):
            (path / 'input.pdf').unlink(missing_ok=True)
            raise PermissionError('file busy')
        with patch('files.lifecycle.shutil.rmtree', side_effect=partial):
            with self.assertRaises(PermissionError):
                cleanup_session(self.score.pk)
        self.score.refresh_from_db()
        self.assertTrue(self.score.deletion_pending)
        self.assertTrue(directory.exists())
        self.assertEqual(self.client.get(f'/api/scores/{self.score.pk}/').status_code, 404)
        self.assertEqual(cleanup_session(self.score.pk), 'deleted')

    def test_database_failure_after_file_deletion_retries_missing_directory(self):
        directory = self.owned(terminal=True)
        self.expire()
        with patch.object(PDFFile, 'delete', side_effect=RuntimeError('database unavailable')):
            with self.assertRaises(RuntimeError):
                cleanup_session(self.score.pk)
        self.assertFalse(directory.exists())
        self.assertTrue(PDFFile.objects.get(pk=self.score.pk).deletion_pending)
        self.assertEqual(cleanup_session(self.score.pk), 'deleted')

    def test_catalog_and_ambiguous_historical_rows_are_excluded(self):
        for kind in ['catalog', 'legacy']:
            directory = self.prepare_score(source_type='audio')
            self.score.retention_kind = kind
            self.score.expires_at = timezone.now() - timedelta(days=90)
            self.score.job_state = 'SUCCESS'
            self.score.save()
            self.assertEqual(cleanup_session(self.score.pk), 'excluded_or_missing')
            self.assertTrue(directory.exists())
        recover_sessions()
        self.assertEqual(PDFFile.objects.count(), 2)

    def test_unrelated_external_compatibility_files_are_never_deleted(self):
        self.owned(terminal=True)
        external = self.root / 'output'
        external.mkdir()
        historical = external / f'output_{self.score.pk}.xml'
        historical.write_bytes(b'historical ownership unknown')
        self.expire(); cleanup_session(self.score.pk)
        self.assertEqual(historical.read_bytes(), b'historical ownership unknown')

    def test_expired_and_unknown_routes_share_honest_response(self):
        self.owned(terminal=True)
        self.expire()
        urls = ['scores/{id}/', 'serve-musicxml/{id}/', 'serve-midi/{id}/', 'serve-preview-midi/{id}/', 'serve-source-audio/{id}/', 'download/{id}/download']
        for deleted in [False, True]:
            if deleted:
                cleanup_session(self.score.pk)
            for score_id in [self.score.pk, 99999999]:
                for url in urls:
                    response = self.client.get('/api/' + url.format(id=score_id))
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json()['code'], 'analysis_unavailable_or_expired')
                response = self.client.post('/api/generate-summary/', {'score_id': score_id}, format='json')
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()['code'], 'analysis_unavailable_or_expired')

    def test_deadline_is_exclusive_and_list_hides_expired_row(self):
        self.owned(terminal=True)
        with patch('files.lifecycle.timezone.now', return_value=self.score.expires_at - timedelta(microseconds=1)):
            self.assertEqual(self.client.get(f'/api/scores/{self.score.pk}/').status_code, 200)
        with patch('files.lifecycle.timezone.now', return_value=self.score.expires_at):
            self.assertEqual(self.client.get(f'/api/scores/{self.score.pk}/').status_code, 404)
            self.assertEqual(self.client.get('/api/files/').data, [])

    def test_delayed_cleanup_never_deletes_active_or_newer_attempt(self):
        self.owned()
        self.score.analysis_task_id = 'new-job'; self.score.save()
        self.assertEqual(cleanup_session(self.score.pk, 'old-job'), 'superseded')
        self.assertEqual(cleanup_session(self.score.pk), 'not_due')
        self.assertTrue((self.root / str(self.score.pk)).exists())
        # Even an obsolete deadline on an active row cannot authorize deletion.
        PDFFile.objects.filter(pk=self.score.pk).update(expires_at=timezone.now() - timedelta(days=1))
        self.assertEqual(cleanup_session(self.score.pk), 'not_due')

    def test_live_writer_lock_protects_recovery_and_deletion(self):
        self.owned()
        PDFFile.objects.filter(pk=self.score.pk).update(job_updated_at=timezone.now() - timedelta(hours=3))
        with session_lock(self.score.pk):
            self.assertEqual(cleanup_session(self.score.pk), 'busy')
            self.assertEqual(recover_sessions(), {'busy': 1})
            with patch('files.views.AsyncResult', return_value=Mock(state='FAILURE')):
                response = self.client.get(f'/api/scores/{self.score.pk}/')
            self.assertEqual(response.data['task_status']['state'], 'QUEUED')
        self.score.refresh_from_db()
        self.assertIsNone(self.score.terminal_at)

    def test_abandoned_job_recovers_and_expires_after_one_hour(self):
        self.owned()
        PDFFile.objects.filter(pk=self.score.pk).update(job_updated_at=timezone.now() - timedelta(hours=3))
        recover_sessions()
        self.score.refresh_from_db()
        self.assertEqual(self.score.job_state, 'FAILURE')
        self.assertEqual(self.score.results['processing']['components']['job']['code'], 'job_progress_timeout')
        self.assertEqual(self.score.expires_at - self.score.terminal_at, timedelta(hours=1))
        with patch('files.lifecycle.timezone.now', return_value=self.score.expires_at):
            recover_sessions()
        self.assertFalse(PDFFile.objects.filter(pk=self.score.pk).exists())

    def test_terminal_redelivery_does_not_extend_expiry_or_reprocess(self):
        self.owned(terminal=True)
        deadline = self.score.expires_at
        process_score.push_request(id='redelivery')
        try:
            with patch('files.tasks.process_with_audiveris') as recognize:
                process_score.run(self.score.pk, 'pdf', 'pdf')
            recognize.assert_not_called()
        finally:
            process_score.pop_request()
        self.score.refresh_from_db()
        self.assertEqual(self.score.expires_at, deadline)

    def test_late_worker_after_deletion_never_recreates_directory_or_row(self):
        directory = self.owned(terminal=True)
        self.expire(); cleanup_session(self.score.pk)
        with patch('files.tasks.process_with_audiveris') as recognize:
            result = process_score.run(self.score.pk, 'pdf', 'pdf')
        self.assertEqual(result['stage'], 'UNAVAILABLE')
        recognize.assert_not_called()
        self.assertFalse(directory.exists())
        self.assertFalse(PDFFile.objects.filter(pk=self.score.pk).exists())

    def test_summary_crossing_expiry_is_discarded_without_resurrection(self):
        self.owned(terminal=True)
        self.score.summary = 'previous'; self.score.save(update_fields=['summary'])
        def late_response(*args, **kwargs):
            self.assertEqual(cleanup_session(self.score.pk), 'busy')
            self.expire()
            return Mock(text='late summary')
        with self.settings(GEMINI_API_KEY='controlled'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.side_effect = late_response
            response = self.client.post('/api/generate-summary/', {'score_id': self.score.pk}, format='json')
        self.assertEqual(response.status_code, 404)
        self.score.refresh_from_db()
        self.assertEqual(self.score.summary, 'previous')
        self.assertEqual(cleanup_session(self.score.pk), 'deleted')

    def test_command_retries_failed_session_and_continues_other_sessions(self):
        self.owned(terminal=True); self.expire()
        first = self.score.pk
        self.owned(terminal=True); self.expire()
        original = shutil.rmtree
        def fail_one(path):
            if path.name == str(first):
                raise PermissionError('busy')
            return original(path)
        output = StringIO()
        with patch('files.lifecycle.shutil.rmtree', side_effect=fail_one):
            call_command('cleanup_analyses', stdout=output)
        self.assertIn("'retry': 1", output.getvalue())
        self.assertTrue(PDFFile.objects.filter(pk=first).exists())
        self.assertFalse(PDFFile.objects.filter(pk=self.score.pk).exists())
        call_command('cleanup_analyses', stdout=StringIO())
        self.assertEqual(PDFFile.objects.count(), 0)

    def test_unexpected_catalog_storage_reference_blocks_deletion(self):
        directory = self.owned(terminal=True)
        self.score.file = 'shared.pdf'; self.score.save(update_fields=['file'])
        self.expire()
        with self.assertRaises(ValueError):
            cleanup_session(self.score.pk)
        self.assertTrue(directory.exists())
        self.assertTrue(PDFFile.objects.filter(pk=self.score.pk).exists())

    def test_unsafe_cleanup_root_is_rejected(self):
        self.owned(terminal=True); self.expire()
        from .references import FIXTURES
        with self.settings(TEMP_STORAGE_DIR=FIXTURES):
            with self.assertRaises(ValueError):
                cleanup_session(self.score.pk)

    def test_owned_analysis_update_cannot_create_catalog_file(self):
        self.owned(terminal=True)
        response = self.client.put(f'/api/update/{self.score.pk}/', {'title': 'replacement',
            'file': SimpleUploadedFile('a.pdf', b'%PDF', content_type='application/pdf')}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.score.refresh_from_db()
        self.assertFalse(self.score.file)

    def test_catalog_worker_is_excluded_without_scheduling_cleanup(self):
        self.prepare_score()
        self.score.retention_kind = 'catalog'; self.score.save()
        with patch('files.tasks.process_with_audiveris') as recognize, patch('files.tasks.cleanup_temp_files.apply_async') as schedule:
            result = process_score.run(self.score.pk, 'pdf', 'pdf')
        self.assertEqual(result['stage'], 'UNAVAILABLE')
        recognize.assert_not_called(); schedule.assert_not_called()

    def test_os_lock_excludes_another_process_and_releases_after_process_death(self):
        import os
        import subprocess
        import sys
        self.owned(terminal=True)
        self.expire()
        script = '''
import sys, django
django.setup()
from django.test import override_settings
from files.lifecycle import session_lock
with override_settings(TEMP_STORAGE_DIR=sys.argv[1]):
    with session_lock(int(sys.argv[2])):
        print('locked', flush=True)
        sys.stdin.read(1)
'''
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='tests.settings')
        process = subprocess.Popen([sys.executable, '-c', script, str(self.root), str(self.score.pk)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            self.assertEqual(cleanup_session(self.score.pk), 'busy')
            process.terminate()
            process.wait(timeout=15)
            # Windows can briefly report the lock busy after process termination.
            # Verify bounded eventual release, as the periodic cleaner also does.
            import time
            deadline = time.monotonic() + 3
            result = cleanup_session(self.score.pk)
            while result == 'busy' and time.monotonic() < deadline:
                time.sleep(0.02)
                result = cleanup_session(self.score.pk)
            self.assertEqual(result, 'deleted')
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=15)
            process.stdin.close(); process.stdout.close(); process.stderr.close()

    def test_cleanup_schedule_outage_preserves_deadline_and_recovery(self):
        self.owned()
        with patch('files.tasks.process_with_audiveris', return_value=(str(self.recognized), {})), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async', side_effect=RuntimeError('broker outage')):
            process_score.run(self.score.pk, 'pdf', 'pdf')
        self.score.refresh_from_db()
        deadline = self.score.expires_at
        self.assertEqual(self.score.job_stage, 'PARTIAL')
        self.assertEqual(self.score.results['processing']['components']['cleanup_scheduling']['code'], 'cleanup_schedule_failed')
        self.assertEqual(deadline - self.score.terminal_at, timedelta(hours=1))
        with patch('files.lifecycle.timezone.now', return_value=deadline):
            self.assertEqual(recover_sessions(), {'deleted': 1})

    def test_catalog_source_update_and_shared_category_survive_sweep(self):
        with patch('files.views.process_score.delay') as dispatch:
            response = self.client.post('/api/upload/', {'title': 'catalog', 'analyze': 'false',
                'file': SimpleUploadedFile('catalog.pdf', b'%PDF catalog', content_type='application/pdf')}, format='multipart')
        dispatch.assert_not_called()
        catalog = PDFFile.objects.get(pk=response.data['score_id'])
        self.assertEqual(catalog.retention_kind, 'catalog')
        path = catalog.file.path
        category = Category.objects.create(name='Both')
        catalog.categories.add(category)
        response = self.client.put(f'/api/update/{catalog.pk}/', {'title': 'updated'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.owned(terminal=True)
        self.score.categories.add(category)
        self.expire(); recover_sessions()
        catalog.refresh_from_db()
        self.assertEqual(catalog.title, 'updated')
        self.assertEqual(catalog.file.storage.open(catalog.file.name).read(), b'%PDF catalog')
        self.assertTrue(catalog.categories.filter(pk=category.pk).exists())
        self.assertEqual([row['id'] for row in self.client.get('/api/files/').data], [catalog.pk])

    def test_recognition_workspace_is_inside_owned_directory(self):
        from files.audiveris_processor import temp_workspace
        directory = self.owned()
        with temp_workspace(str(self.score.pk)) as workspace:
            from pathlib import Path
            self.assertEqual(Path(workspace).parent, directory)
            (Path(workspace) / 'work.omr').write_bytes(b'owned')
        self.assertFalse(Path(workspace).exists())

    def test_task_metadata_is_forgotten_with_ttl_fallback_on_outage(self):
        for fail in [False, True]:
            self.owned(terminal=True)
            self.score.analysis_task_id = 'owned-task'; self.score.save(update_fields=['analysis_task_id'])
            self.expire()
            with patch('celery.result.AsyncResult') as result:
                if fail:
                    result.return_value.forget.side_effect = RuntimeError('backend down')
                self.assertEqual(cleanup_session(self.score.pk), 'deleted')
                result.assert_called_once_with('owned-task')
                result.return_value.forget.assert_called_once()

    def test_successful_summary_does_not_extend_terminal_deadline(self):
        self.owned(terminal=True)
        deadline, terminal = self.score.expires_at, self.score.terminal_at
        with self.settings(GEMINI_API_KEY='controlled'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.return_value = Mock(text='summary')
            response = self.client.post('/api/generate-summary/', {'score_id': self.score.pk}, format='json')
        self.assertEqual(response.status_code, 200)
        self.score.refresh_from_db()
        self.assertEqual((self.score.expires_at, self.score.terminal_at), (deadline, terminal))

    def test_open_racing_file_deletion_returns_honest_404(self):
        self.owned(terminal=True)
        with patch('files.views.open', side_effect=FileNotFoundError('concurrent deletion'), create=True):
            for role in ['musicxml', 'midi']:
                response = self.client.get(f'/api/serve-{role}/{self.score.pk}/')
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()['code'], 'analysis_unavailable_or_expired')

    def test_owned_terminal_missing_deadline_recovers_without_inventing_old_date(self):
        self.owned(terminal=True)
        PDFFile.objects.filter(pk=self.score.pk).update(terminal_at=None, expires_at=None)
        before = timezone.now()
        recover_sessions()
        self.score.refresh_from_db()
        self.assertGreaterEqual(self.score.terminal_at, before)
        self.assertEqual(self.score.expires_at - self.score.terminal_at, timedelta(hours=1))
