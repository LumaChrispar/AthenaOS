import asyncio
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '16_Runtime'))
from job_runner import JobRunner, create_job
from memory_manager import MemoryManager
from orchestrator import Orchestrator
from llm_client import AthenaLLMClient
from types import SimpleNamespace
from unittest.mock import Mock
from book_library import edit_book, continue_book
from job_runner import atomic_json


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail_service = None
        self.reject = False
        self.invalid_intake = False

    def execute_prompt(self, service, system, prompt):
        self.calls.append(service)
        if service == self.fail_service:
            self.fail_service = None
            raise RuntimeError('simulated interruption')
        chapter = {'id': 'CHAP', 'title': 'Arrival', 'prose_content': 'She opened the door. The sea answered. She stayed.',
                   'summary': 'A visitor arrives.', 'objective': 'Arrival', 'cliffhanger': 'Who waits?', 'continuity_notes': []}
        if service == 'SRV-001':
            return 'broken JSON' if self.invalid_intake else json.dumps({'decision': 'APPROVED'})
        if service == 'SRV-002':
            if 'Break this single chapter beat' in prompt:
                return json.dumps({'title': 'Arrival', 'summary': 'A visitor arrives.',
                    'scenes': [{'title': 'Arrival', 'pov_character': 'Visitor', 'location': 'Door',
                                'goal': 'Enter', 'conflict': 'Locked door', 'turn': 'The door opens'}] * 3})
            return json.dumps({'title': 'The Door', 'beat_sheets': [{'act': 1, 'beats': [
                {'goal': 'Arrive', 'conflict': 'A locked door', 'outcome': 'Enter'},
                {'goal': 'Resolve', 'conflict': 'The sea', 'outcome': 'Return'}]}]})
        if service == 'SRV-003':
            return json.dumps({'characters': [{'name': 'Visitor', 'psychology': {'want': 'Enter'}}]})
        if service == 'SRV-004':
            return json.dumps({'locations': ['Door'], 'rules': []})
        if 'edits' in prompt and service in ('SRV-005', 'SRV-027', 'SRV-008'):
            if service == 'SRV-008':
                return json.dumps({'edits': [{'target_text': 'She opened the door.',
                    'replacement': 'She opened the door. COPYEDITED ENDING.'}]})
            return '{"edits": []}'
        if service == 'SRV-005' and 'Return only polished scene prose' in prompt:
            return 'She opened the door.' if '"scene_number": 1' in prompt else 'The sea answered.' if '"scene_number": 2' in prompt else 'She stayed.'
        if service in ('SRV-005', 'SRV-027', 'SRV-008'):
            if service == 'SRV-008':
                chapter['prose_content'] += ' COPYEDITED ENDING.'
            return json.dumps(chapter)
        if service in ('SRV-007', 'SRV-016'):
            return json.dumps({'score': 9})
        if service == 'SRV-010':
            return json.dumps({'score': 9, 'decision': 'REJECTED' if self.reject else 'APPROVED', 'defects': []})
        if service == 'SRV-009' and 'Extract facts' in prompt:
            return json.dumps({'summary': {'events': ['Arrival'], 'foreshadowing_planted': []}, 'bible_updates': {}})
        if service == 'SRV-019':
            return json.dumps({'title': 'The Door', 'blurb': 'A mystery.', 'keywords': []})
        return '{}'


class WorkflowTests(unittest.TestCase):
    def test_dialogue_json_retries_keep_voice_and_draft_checkpoints(self):
        job = create_job(self.root, 'A door by the sea', 2)
        original = self.model.execute_prompt
        audits = []
        def reply(service, system, prompt):
            if service == 'SRV-013':
                self.model.calls.append(service)
                audits.append(service)
                return '{"flagged_lines": [broken}' if len(audits) == 1 else 'Audit follows:\n```json\n{"flagged_lines": [], "rewrite_proposals": []}\n```'
            return original(service, system, prompt)
        self.model.execute_prompt = reply
        self.run_job(job)
        self.assertEqual(self.model.calls.count('SRV-027'), 2)
        self.assertEqual(self.model.calls.count('SRV-013'), 3)
        audit = json.loads((job / '08_Memory/dialogue_audit_chapter_01.json').read_text())
        self.assertEqual(audit['flagged_lines'], [])
        self.assertEqual(json.loads((job / 'job.json').read_text())['status'], 'completed')

    def test_resume_review_interruption_keeps_chapter_operations(self):
        job = create_job(self.root, 'A door by the sea', 2)
        self.model.fail_service = 'SRV-010'
        with self.assertRaises(RuntimeError):
            self.run_job(job)
        self.run_job(job)
        self.assertEqual(self.model.calls.count('SRV-027'), 2)
        self.assertEqual(self.model.calls.count('SRV-013'), 2)
        self.assertEqual(self.model.calls.count('SRV-007'), 2)
        self.assertEqual(json.loads((job / 'job.json').read_text())['status'], 'completed')

    def test_missing_provider_choices_are_retried_without_type_error(self):
        job = create_job(self.root, 'First')
        client = AthenaLLMClient.__new__(AthenaLLMClient)
        client.capability_model = {}
        client.default_model = 'fake'
        client.default_temp = .5
        client.usage_path = str(job / '08_Memory/usage.json')
        client.max_calls = 10
        client.max_output_tokens = 100
        client.client = Mock()
        good = SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{}'))])
        client.client.chat.completions.create.side_effect = [SimpleNamespace(choices=None), None, good]
        with patch('llm_client.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(client.execute_prompt('SRV-001', 'system', 'user'), '{}')
        self.assertEqual(client.client.chat.completions.create.call_count, 3)
        self.assertEqual(json.loads(Path(client.usage_path).read_text())['calls'], 3)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ('config', '06_Services', '08_Memory/schemas'):
            shutil.copytree(ROOT / folder, self.root / folder)
        self.model = FakeModel()
        self.patcher = patch('orchestrator.AthenaLLMClient', return_value=self.model)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def run_job(self, job):
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(JobRunner(job).run())

    def test_end_to_end_delivers_copyedited_prose_and_no_repeat_on_resume(self):
        job = create_job(self.root, 'A door by the sea', 2)
        self.run_job(job)
        state = json.loads((job / 'job.json').read_text())
        self.assertEqual(state['status'], 'completed')
        manuscript = (job / '08_Memory/manuscript.md').read_text()
        self.assertEqual(manuscript.count('COPYEDITED ENDING.'), 2)
        self.assertNotIn('SRV-020', self.model.calls)
        calls = list(self.model.calls)
        self.run_job(job)
        self.assertEqual(self.model.calls, calls)

    def test_resume_after_planning_interruption(self):
        job = create_job(self.root, 'A door by the sea', 2)
        self.model.fail_service = 'SRV-004'
        with self.assertRaises(RuntimeError):
            self.run_job(job)
        self.assertEqual(json.loads((job / 'job.json').read_text())['status'], 'failed')
        self.run_job(job)
        self.assertEqual(self.model.calls.count('SRV-002'), 3)  # outline once, two scene plans
        self.assertEqual(self.model.calls.count('SRV-003'), 1)
        self.assertEqual(self.model.calls.count('SRV-004'), 2)

    def test_resume_after_delivery_interruption_skips_completed_chapters(self):
        job = create_job(self.root, 'A door by the sea', 2)
        self.model.fail_service = 'SRV-019'
        with self.assertRaises(RuntimeError):
            self.run_job(job)
        drafting_calls = self.model.calls.count('SRV-005')
        self.run_job(job)
        self.assertEqual(self.model.calls.count('SRV-005'), drafting_calls)

    def test_qa_rejection_blocks_delivery_even_with_high_scores(self):
        job = create_job(self.root, 'A door by the sea', 2)
        self.model.reject = True
        with self.assertRaises(RuntimeError):
            self.run_job(job)
        self.assertEqual(self.model.calls.count('SRV-010'), 3)
        self.assertEqual(self.model.calls.count('SRV-027'), 1)
        self.assertNotIn('SRV-008', self.model.calls)
        self.assertFalse((job / '08_Memory/manuscript.md').exists())

    def test_invalid_intake_never_approves_and_retries_are_bounded(self):
        job = create_job(self.root, 'A door by the sea', 2)
        self.model.invalid_intake = True
        with self.assertRaises(ValueError):
            self.run_job(job)
        self.assertEqual(self.model.calls, ['SRV-001'] * 3)
        self.assertNotIn('intake', json.loads((job / 'job.json').read_text())['completed_steps'])

    def test_jobs_are_isolated_and_old_artifacts_are_not_imported(self):
        a = create_job(self.root, 'First')
        b = create_job(self.root, 'Second')
        MemoryManager(str(a)).save_artifact('outline.json', '{"title":"First"}')
        self.assertFalse((b / '08_Memory/outline.json').exists())
        self.assertNotEqual(a, b)

    def test_chapter_summary_cannot_be_saved_as_prose(self):
        job = create_job(self.root, 'First')
        with self.assertRaises(ValueError):
            MemoryManager(str(job)).save_artifact('chapter_01.json', '{"summary":"Only a summary"}')

    def test_incomplete_manuscript_cannot_be_formatted(self):
        job = create_job(self.root, 'First')
        orch = Orchestrator(str(job))
        orch.pipeline_state.update(total_chapters=2, last_completed_chapter=1)
        with self.assertRaises(ValueError):
            asyncio.run(orch.run_formatting())

    def test_conditional_intake_resolves_format_and_delegates_outline(self):
        job = create_job(self.root, 'Shakespearean horror with witches who create prophecies', 4)
        prior = {'decision': 'CONDITIONAL', 'rationale': 'Confirm novella format and provide an outline.',
                 'conditions_for_approval': ['Confirm four chapters', 'Supply outline', 'Differentiate from Macbeth']}
        MemoryManager(str(job)).save_artifact('ceo_intake_decision.json', json.dumps(prior))
        orch = Orchestrator(str(job))
        with patch.object(self.model, 'execute_prompt', side_effect=[json.dumps(prior), json.dumps({
            'decision': 'APPROVED', 'assumptions': ['Four short chapters'],
            'planning_instructions': ['Create an original tragic arc']} )]) as execute:
            result = asyncio.run(orch.run_ceo_intake('Witches create prophecies. Four chapters.'))
            self.assertEqual(result['decision'], 'APPROVED')
            self.assertEqual(execute.call_count, 2)
            self.assertIn('not gates', execute.call_args.args[1])
            self.assertIn('Confirm novella format', execute.call_args_list[0].args[2])
            self.assertIn('Resolve routine conditions yourself', execute.call_args.args[2])
        brief = json.loads((job / '08_Memory/intake_brief.json').read_text())
        self.assertEqual(brief['requested_chapters'], 4)
        self.assertEqual(brief['suggested_total_words'], 12000)

    def test_unresolved_intake_conditions_remain_blocking_after_three_attempts(self):
        job = create_job(self.root, 'A story', 2)
        with patch.object(self.model, 'execute_prompt', return_value=json.dumps({
            'decision': 'CONDITIONAL', 'rationale': 'Contradictory requirements remain unresolved.'})) as execute:
            with self.assertRaises(RuntimeError):
                self.run_job(job)
            self.assertEqual(execute.call_count, 3)
        self.assertNotIn('intake', json.loads((job / 'job.json').read_text())['completed_steps'])

    def test_intake_without_explicit_decision_is_never_approved(self):
        job = create_job(self.root, 'A story', 2)
        with patch.object(self.model, 'execute_prompt', return_value='{"rationale":"Looks fine"}'):
            with self.assertRaises(ValueError):
                self.run_job(job)
        self.assertNotIn('intake', json.loads((job / 'job.json').read_text())['completed_steps'])

    def test_request_limit_persists_across_client_instances(self):
        job = create_job(self.root, 'First')
        path = str(job / '08_Memory/usage.json')
        def client():
            result = AthenaLLMClient.__new__(AthenaLLMClient)
            result.capability_model = {}
            result.default_model = 'fake'
            result.default_temp = 0.5
            result.usage_path = path
            result.max_calls = 1
            result.max_output_tokens = 100
            result.client = Mock()
            result.client.chat.completions.create.return_value = SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
                choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{}'))])
            return result
        first = client()
        first.execute_prompt('SRV-001', 'system', 'user')
        second = client()
        with self.assertRaisesRegex(RuntimeError, 'limit reached'):
            second.execute_prompt('SRV-001', 'system', 'user')
        second.client.chat.completions.create.assert_not_called()
        self.assertEqual(json.loads(Path(path).read_text())['completion_tokens'], 2)

    def test_second_worker_cannot_run_same_job(self):
        job = create_job(self.root, 'First')
        class LockProbe(Orchestrator):
            async def run_ceo_intake(inner, concept):
                with self.assertRaisesRegex(RuntimeError, 'Another worker'):
                    await JobRunner(job).run()
                return await super(LockProbe, inner).run_ceo_intake(concept)
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(JobRunner(job, LockProbe).run())

    def test_saved_chapter_roadmap_recovers_without_new_outline_call(self):
        job = create_job(self.root, 'A story', 2)
        MemoryManager(str(job)).save_artifact('outline.json', json.dumps({
            'title': 'Recovered', 'chapter_roadmap': [
                {'goal': 'Arrive', 'conflict': 'Locked door', 'outcome': 'Enter'},
                {'goal': 'Resolve', 'conflict': 'Sea', 'outcome': 'Return'}]}))
        self.run_job(job)
        self.assertEqual(self.model.calls.count('SRV-002'), 2)  # scene plans only
        outline = json.loads((job / '08_Memory/outline.json').read_text())
        self.assertEqual(len(outline['beat_sheets'][0]['beats']), 2)

    def test_edit_and_continue_preserves_prose_and_adds_chapters(self):
        job = create_job(self.root, 'A story', 2)
        self.run_job(job)
        edit_book(job, {'kind': 'chapter', 'number': 1, 'title': 'My title', 'text': 'My revised opening.'})
        self.assertIn('My revised opening.', (job / '08_Memory/manuscript.md').read_text())
        self.assertTrue(list((job / 'revisions').glob('*/08_Memory/manuscript.md')))
        drafting = self.model.calls.count('SRV-005')
        continue_book(job, 'A return to the sea', 2)
        self.run_job(job)
        # SRV-005 handles both the draft and dialogue rewrite for each new chapter.
        self.assertEqual(self.model.calls.count('SRV-005'), drafting * 2)
        manuscript = (job / '08_Memory/manuscript.md').read_text()
        self.assertIn('My revised opening.', manuscript)
        self.assertIn('Chapter 4:', manuscript)
        self.assertEqual(json.loads((job / 'job.json').read_text())['status'], 'completed')

    def test_deleted_job_never_starts_model(self):
        job = create_job(self.root, 'A story')
        state = json.loads((job / 'job.json').read_text())
        state['deleted_at'] = 123
        atomic_json(job / 'job.json', state)
        self.run_job(job)
        self.assertEqual(self.model.calls, [])

    def test_truncated_output_is_not_repeated_unchanged(self):
        job = create_job(self.root, 'A story')
        client = AthenaLLMClient.__new__(AthenaLLMClient)
        client.capability_model = {}
        client.default_model, client.default_temp = 'fake', 0.5
        client.usage_path = str(job / '08_Memory/usage.json')
        client.max_calls, client.max_output_tokens = 10, 100
        client.client = Mock()
        client.client.chat.completions.create.return_value = SimpleNamespace(usage=None,
            choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(content='{"partial":'))])
        with self.assertRaisesRegex(RuntimeError, 'context limit'):
            client.execute_prompt('SRV-001', 'system', 'user')
        self.assertEqual(client.client.chat.completions.create.call_count, 1)

    def test_provider_aware_context_limit_messages(self):
        job = create_job(self.root, 'A story')
        cases = [
            ('ollama', 'also check its loaded context length in Ollama'),
            ('lmstudio', 'also check its loaded context length in LM Studio'),
            ('openrouter', 'for OpenRouter, also choose a model with a larger context limit or lower the output limit'),
            ('openai', 'for OpenAI, also choose a model with a larger context limit or lower the output limit'),
            ('google', 'for Google Gemini, also choose a model with a larger context limit or lower the output limit'),
            ('groq', 'for Groq, also choose a model with a larger context limit or lower the output limit'),
            (None, 'also check its loaded context length in LM Studio or Ollama'),
        ]
        for provider, expected_hint in cases:
            with self.subTest(provider=provider):
                client = AthenaLLMClient.__new__(AthenaLLMClient)
                client.capability_model = {}
                client.default_model, client.default_temp = 'fake', 0.5
                client.usage_path = str(job / '08_Memory/usage.json')
                client.max_calls, client.max_output_tokens = 10, 100
                if provider:
                    client.provider = provider
                client.client = Mock()
                client.client.chat.completions.create.return_value = SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(content='{"partial":'))]
                )
                with self.assertRaises(RuntimeError) as caught:
                    client.execute_prompt('SRV-001', 'system', 'user')
                self.assertIn('context limit', str(caught.exception))
                self.assertIn(expected_hint, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
