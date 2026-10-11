"""Offline behavior tests using a fake CLI, without model requests."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_phase.py"
CHECKER = RUNNER.with_name("check_run.py")
sys.path.insert(0, str(RUNNER.parent))
from check_run import check_run
FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
session = args[args.index('--resume' if '--resume' in args else '--session-id') + 1]
Path('fake-started').write_text(str(os.getpid()))
Path('fake-args.json').write_text(json.dumps(args))
if 'TEST_DESCENDANT' in prompt:
    child = "import signal,time; from pathlib import Path; " \
            "signal.signal(signal.SIGTERM, lambda *a: (time.sleep(.3), Path('cleaned').write_text('yes'), exit(0))); " \
            "Path('child-started').touch(); time.sleep(60)"
    subprocess.Popen([sys.executable, '-c', child])
    time.sleep(60)
if 'TEST_SLEEP' in prompt: time.sleep(60)
if 'TEST_NONZERO' in prompt:
    print('authentication failed', file=sys.stderr)
    sys.exit(7)
if 'TEST_BAD_JSON' in prompt:
    print('bad json')
    sys.exit(0)
report = dict(status='blocked' if 'TEST_BLOCKED' in prompt else 'ready_for_review',
              summary='Implemented fixture', changed_files=['fixture.txt'],
              verification=['fixture check: passed'], limitations=[], permission_requests=[])
if 'TEST_REQUEST' in prompt:
    report['status'] = 'needs_permission'
    report['permission_requests'] = [dict(id='P1', command='echo "$(touch NEVER_EXECUTE)"',
        cwd=str(Path.cwd()), reason='Need a check', expected_effects='Creates a test marker')]
if 'TEST_EMPTY_REQUEST' in prompt: report['status'] = 'needs_permission'
if 'TEST_RELATIVE_CWD' in prompt: report['permission_requests'][0]['cwd'] = '.'
if 'TEST_DUPLICATE_ID' in prompt: report['permission_requests'] *= 2
if 'TEST_EMPTY_REASON' in prompt: report['permission_requests'][0]['reason'] = ' '
if 'TEST_HIDDEN_REQUEST' in prompt: report['status'] = 'ready_for_review'
if 'TEST_FAILED' in prompt: report['status'] = 'failed'
result = dict(type='result', subtype='success', is_error=False, session_id=session,
              structured_output=report, modelUsage={'claude-opus-5-5': {}},
              total_cost_usd=0.1)
if 'TEST_MISMATCH' in prompt: result['session_id'] = 'wrong'
if 'TEST_DENIED' in prompt:
    result['permission_denials'] = [{'tool_name': 'Bash', 'tool_use_id': 'denied-1',
                                   'tool_input': {'command': 'make test 2>&1'}}]
if 'TEST_ERROR' in prompt: result.update(is_error=True, subtype='error_max_turns')
if 'TEST_NO_REPORT' in prompt: del result['structured_output']
if 'TEST_API' in prompt:
    result.update(is_error=True, terminal_reason='api_error',
                  api_error_status=401 if 'TEST_AUTH' in prompt else 429,
                  result='SECRET_CANARY raw provider message')
    del result['structured_output']
    print(json.dumps(result), flush=True)
    sys.exit(0 if 'TEST_ZERO' in prompt else 1)
print(json.dumps(result))
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'workspace with spaces'
        self.workspace.mkdir()
        self.fake = self.root / 'fake-claude'
        self.fake.write_text(FAKE)
        self.fake.chmod(0o700)
        self.count = 0

    def tearDown(self):
        self.temp.cleanup()

    def command(self, content='Implement a fixture.', extra=()):
        self.count += 1
        brief = self.root / ('brief-%s.md' % self.count)
        brief.write_text(content)
        run = self.root / ('run-%s' % self.count)
        cmd = [sys.executable, str(RUNNER), '--workspace', str(self.workspace),
               '--brief', str(brief), '--run-dir', str(run), '--claude-bin', str(self.fake)]
        return cmd + list(extra), run

    def run_phase(self, content='Implement a fixture.', extra=()):
        cmd, run = self.command(content, extra)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result, run

    def metadata(self, run):
        return json.loads((run / 'metadata.json').read_text())

    def wait_started(self, proc):
        deadline = time.monotonic() + 5
        while not (self.workspace / 'fake-started').exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                self.fail('fake CLI did not start')
            time.sleep(0.02)

    def test_success_default_model_and_literal_stdin(self):
        content = 'Keep literal $(touch INJECTED) and `touch ALSO_INJECTED`.'
        result, run = self.run_phase(content, ['--allow-tool', 'Bash(npm test *)'])
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = self.metadata(run)
        self.assertEqual(meta['model'], 'claude-opus-5-5')
        self.assertTrue(meta['session_confirmed'])
        self.assertEqual(meta['status'], 'ready_for_review')
        self.assertIn(content, (run / 'prompt.md').read_text())
        self.assertIn('Bash(npm test *)', (run / 'prompt.md').read_text())
        self.assertTrue((run / 'report.md').exists())
        self.assertFalse((self.workspace / 'INJECTED').exists())
        args = json.loads((self.workspace / 'fake-args.json').read_text())
        self.assertEqual(args[args.index('--effort') + 1], 'medium')
        self.assertNotIn(content, args)
        self.assertNotIn('--dangerously-skip-permissions', args)

    def test_resume_exact_session_and_preserve_previous(self):
        first, run1 = self.run_phase()
        before = (run1 / 'metadata.json').read_bytes()
        second, run2 = self.run_phase('Fix review findings.', ['--resume-from', str(run1)])
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(self.metadata(run1)['session_id'], self.metadata(run2)['session_id'])
        self.assertEqual(before, (run1 / 'metadata.json').read_bytes())
        self.assertIn('--resume', self.metadata(run2)['command'])
        args = json.loads((self.workspace / 'fake-args.json').read_text())
        self.assertEqual(args[args.index('--effort') + 1], 'medium')

    def test_explicit_effort_override_on_new_session_and_resume(self):
        first, run1 = self.run_phase(extra=['--effort', 'high'])
        self.assertEqual(first.returncode, 0, first.stderr)
        args = json.loads((self.workspace / 'fake-args.json').read_text())
        self.assertEqual(args[args.index('--effort') + 1], 'high')
        second, _ = self.run_phase(extra=['--resume-from', str(run1), '--effort', 'high'])
        self.assertEqual(second.returncode, 0, second.stderr)
        args = json.loads((self.workspace / 'fake-args.json').read_text())
        self.assertEqual(args[args.index('--effort') + 1], 'high')

    def test_resume_rejects_changed_model_or_workspace(self):
        _, prior = self.run_phase()
        other = self.root / 'other'
        other.mkdir()
        for change in (['--model', 'sonnet'], ['--workspace', str(other)]):
            with self.subTest(change=change):
                result, run = self.run_phase(extra=['--resume-from', str(prior)] + change)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(run.exists())

    def test_protocol_and_process_errors_keep_evidence(self):
        for mode in ('BAD_JSON', 'MISMATCH', 'ERROR', 'NO_REPORT', 'NONZERO'):
            with self.subTest(mode=mode):
                result, run = self.run_phase('TEST_' + mode)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.metadata(run)['status'], 'error')
                self.assertTrue((run / 'stdout.json').exists())
                self.assertFalse((run / 'report.json').exists())
                if mode == 'NONZERO':
                    self.assertEqual(self.metadata(run)['claude_exit_code'], 7)

    def test_blocked_is_distinct_from_permission_request(self):
        result, run = self.run_phase('TEST_BLOCKED')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.metadata(run)['status'], 'blocked')
        self.assertFalse((run / 'permission-request.json').exists())

    def test_api_failure_without_report_reaches_astra(self):
        for flags, kind, status, child_code in [
                ('', 'api_rate_limit', 429, 1),
                ('TEST_ZERO', 'api_rate_limit', 429, 0),
                ('TEST_AUTH', 'api_auth', 401, 1)]:
            with self.subTest(flags=flags):
                result, run = self.run_phase('TEST_API ' + flags)
                self.assertEqual(result.returncode, 2)
                meta = self.metadata(run)
                self.assertEqual(meta['process_state'], 'exited')
                self.assertEqual(meta['failure_kind'], kind)
                self.assertEqual(meta['api_status'], status)
                self.assertEqual(meta['claude_exit_code'], child_code)
                self.assertIsNone(meta['task_status'])
                self.assertFalse(meta['report_available'])
                self.assertFalse((run / 'report.json').exists())
                summary = json.loads(result.stdout)
                self.assertEqual(summary['failure_kind'], kind)
                self.assertNotIn('SECRET_CANARY', result.stdout)
                self.assertIn('SECRET_CANARY', (run / 'stdout.json').read_text())

    def test_checker_recovers_terminal_state_without_wait_output(self):
        _, run = self.run_phase('TEST_API')
        before = {p.name: p.read_bytes() for p in run.iterdir()}
        result = subprocess.run([sys.executable, str(CHECKER), '--run-dir', str(run),
                                 '--session-id', self.metadata(run)['session_id']],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertTrue(summary['terminal'])
        self.assertEqual(summary['process_state'], 'exited')
        self.assertEqual(summary['failure_kind'], 'api_rate_limit')
        self.assertFalse(summary['report_available'])
        self.assertNotIn('SECRET_CANARY', result.stdout)
        self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})

    def test_checker_distinguishes_report_and_process_completion(self):
        for flags, expected in [('', 'ready_for_review'), ('TEST_FAILED', 'failed'),
                                ('TEST_REQUEST', 'needs_permission'), ('TEST_BLOCKED', 'blocked')]:
            with self.subTest(flags=flags):
                _, run = self.run_phase(flags or 'Implement fixture')
                summary = check_run(run)
                self.assertTrue(summary['terminal'])
                self.assertEqual(summary['task_status'], expected)
                self.assertTrue(summary['report_available'])

    def test_checker_legacy_terminal_metadata_and_session_binding(self):
        _, run = self.run_phase('TEST_NONZERO')
        meta = self.metadata(run)
        for field in ['process_state', 'task_status', 'failure_kind', 'api_status',
                      'report_available', 'heartbeat_at']:
            meta.pop(field)
        (run / 'metadata.json').write_text(json.dumps(meta))
        self.assertTrue(check_run(run)['terminal'])
        wrong = check_run(run, '00000000-0000-0000-0000-000000000000')
        self.assertFalse(wrong['terminal'])
        self.assertEqual(wrong['reason'], 'session_mismatch')

    def test_checker_missing_corrupt_and_cleanup_state(self):
        run = self.root / 'checker-run'
        run.mkdir()
        for content in [None, 'not json', '[]', '{"session_id": null}',
                        '{"session_id":"00000000-0000-0000-0000-000000000000","status":[]}']:
            with self.subTest(content=content):
                if content is not None:
                    (run / 'metadata.json').write_text(content)
                summary = check_run(run)
                self.assertEqual(summary['process_state'], 'unknown')
                self.assertFalse(summary['terminal'])
        meta = dict(session_id='00000000-0000-0000-0000-000000000000',
                    status='cleanup_error', runner_exit_code=2, finished_at=time.time())
        (run / 'metadata.json').write_text(json.dumps(meta))
        summary = check_run(run)
        self.assertTrue(summary['terminal'])
        self.assertEqual(summary['process_state'], 'unknown')
        self.assertEqual(summary['reason'], 'cleanup_unconfirmed')

    def test_heartbeat_is_local_and_runner_death_does_not_imply_child_death(self):
        cmd, run = self.command('TEST_SLEEP')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child_pid = None
        try:
            self.wait_started(proc)
            first = self.metadata(run)
            child_pid = first['claude_pid']
            deadline = time.monotonic() + 8
            while self.metadata(run)['heartbeat_at'] == first['heartbeat_at']:
                if proc.poll() is not None or time.monotonic() > deadline:
                    self.fail('runner heartbeat did not advance')
                time.sleep(.05)
            meta = self.metadata(run)
            self.assertEqual(check_run(run)['process_state'], 'running')
            proc.kill()
            output, _ = proc.communicate(timeout=5)
            self.assertEqual(output, b'')
            os.kill(child_pid, 0)
            summary = check_run(run, now=meta['heartbeat_at'] + 21)
            self.assertFalse(summary['terminal'])
            self.assertEqual(summary['process_state'], 'unknown')
            self.assertEqual(summary['reason'], 'stale_heartbeat')
        finally:
            if child_pid is not None:
                try:
                    os.killpg(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_proactive_request_is_saved_without_execution_or_grant(self):
        result, run = self.run_phase('TEST_REQUEST')
        self.assertEqual(result.returncode, 4, result.stderr)
        meta = self.metadata(run)
        self.assertEqual(meta['status'], 'needs_permission')
        request = json.loads((run / 'permission-request.json').read_text())
        self.assertEqual(request['session_id'], meta['session_id'])
        self.assertEqual(request['workspace'], str(self.workspace))
        self.assertEqual(request['requests'][0]['command'], 'echo "$(touch NEVER_EXECUTE)"')
        self.assertEqual(request['cli_denials'], [])
        self.assertFalse((self.workspace / 'NEVER_EXECUTE').exists())
        self.assertEqual(meta['command'][meta['command'].index('--allowedTools') + 1],
                         'Read,Glob,Grep,Edit,Write')
        self.assertEqual(json.loads(result.stdout)['permission_request_path'],
                         str(run / 'permission-request.json'))

    def test_cli_denial_without_worker_request_reaches_astra(self):
        result, run = self.run_phase('TEST_DENIED')
        self.assertEqual(result.returncode, 4)
        self.assertEqual(self.metadata(run)['status'], 'needs_permission')
        request = json.loads((run / 'permission-request.json').read_text())
        self.assertEqual(request['requests'], [])
        self.assertEqual(request['cli_denials'][0]['tool_input']['command'], 'make test 2>&1')

    def test_request_cannot_be_hidden_as_success_or_mask_failure(self):
        for mode, status, code in [('TEST_HIDDEN_REQUEST', 'needs_permission', 4),
                                   ('TEST_FAILED', 'failed', 2)]:
            with self.subTest(mode=mode):
                result, run = self.run_phase('TEST_REQUEST TEST_DENIED ' + mode)
                self.assertEqual(result.returncode, code)
                self.assertEqual(self.metadata(run)['status'], status)
                self.assertTrue((run / 'permission-request.json').exists())

    def test_malformed_requests_fail_closed(self):
        for content in ['TEST_EMPTY_REQUEST', 'TEST_REQUEST TEST_RELATIVE_CWD',
                        'TEST_REQUEST TEST_DUPLICATE_ID', 'TEST_REQUEST TEST_EMPTY_REASON']:
            with self.subTest(content=content):
                result, run = self.run_phase(content)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.metadata(run)['status'], 'error')
                self.assertTrue((run / 'stdout.json').exists())

    def test_decision_resume_uses_same_session_and_only_explicit_rules(self):
        _, prior = self.run_phase('TEST_REQUEST', ['--allow-tool', 'Bash(make)'])
        before = (prior / 'permission-request.json').read_bytes()
        for rules, decision in [([], 'P1 refused. Skip that optional probe.'),
                                (['Bash(make)', 'Bash(make test)'],
                                 'P1 replaced: run make test instead; authorized local test.')]:
            with self.subTest(decision=decision):
                extra = ['--resume-from', str(prior), '--effort', 'medium']
                for rule in rules:
                    extra += ['--allow-tool', rule]
                result, run = self.run_phase(decision, extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                meta = self.metadata(run)
                self.assertEqual(meta['session_id'], self.metadata(prior)['session_id'])
                args = meta['command']
                self.assertEqual(args[args.index('--allowedTools') + 1],
                                 ','.join(['Read', 'Glob', 'Grep', 'Edit', 'Write'] + rules))
                self.assertEqual(args[args.index('--effort') + 1], 'medium')
                self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk')
                self.assertNotIn('--dangerously-skip-permissions', args)
                self.assertIn(decision, (run / 'prompt.md').read_text())
                self.assertFalse((run / 'permission-request.json').exists())
        self.assertEqual(before, (prior / 'permission-request.json').read_bytes())

    def test_relative_executable_is_resolved_before_chdir(self):
        cmd, run = self.command(extra=['--claude-bin', './fake-claude'])
        result = subprocess.run(cmd, cwd=self.root, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.metadata(run)['command'][0], str(self.fake))

    def test_failed_task_keeps_report_without_claiming_success(self):
        result, run = self.run_phase('TEST_FAILED')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.metadata(run)['status'], 'failed')
        self.assertEqual(json.loads((run / 'report.json').read_text())['status'], 'failed')

    def test_existing_run_directory_is_never_overwritten(self):
        cmd, run = self.command()
        run.mkdir()
        (run / 'keep').write_text('user data')
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((run / 'keep').read_text(), 'user data')
        self.assertFalse((self.workspace / 'fake-started').exists())

    def test_read_only_tool_policy(self):
        result, run = self.run_phase(extra=['--read-only'])
        self.assertEqual(result.returncode, 0)
        args = self.metadata(run)['command']
        self.assertEqual(args[args.index('--allowedTools') + 1], 'Read,Glob,Grep')
        self.assertIn('Edit', args[args.index('--disallowedTools') + 1])

    def test_timeout_reaps_worker_and_releases_lock(self):
        result, run = self.run_phase('TEST_SLEEP', ['--timeout-seconds', '0.2'])
        self.assertEqual(result.returncode, 124)
        pid = self.metadata(run)['claude_pid']
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        next_result, _ = self.run_phase()
        self.assertEqual(next_result.returncode, 0)

    def test_descendant_gets_cleanup_grace(self):
        cmd, run = self.command('TEST_DESCENDANT')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not (self.workspace / 'child-started').exists():
                if proc.poll() is not None or time.monotonic() > deadline:
                    self.fail('descendant did not start')
                time.sleep(.02)
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 143)
            self.assertEqual((self.workspace / 'cleaned').read_text(), 'yes')
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_lock_and_sigterm(self):
        cmd, run = self.command('TEST_SLEEP')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_started(proc)
            second, run2 = self.run_phase()
            self.assertEqual(second.returncode, 2)
            self.assertIn('another runner', second.stderr)
            self.assertFalse(run2.exists())
            proc.send_signal(signal.SIGTERM)
            output, errors = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 143, (output, errors, self.metadata(run)))
            self.assertEqual(self.metadata(run)['status'], 'interrupted')
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


if __name__ == '__main__':
    unittest.main()
