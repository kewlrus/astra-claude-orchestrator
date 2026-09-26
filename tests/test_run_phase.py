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
              verification=['fixture check: passed'], limitations=[])
if 'TEST_FAILED' in prompt: report['status'] = 'failed'
result = dict(type='result', subtype='success', is_error=False, session_id=session,
              structured_output=report, modelUsage={'claude-opus-5-5': {}},
              total_cost_usd=0.1)
if 'TEST_MISMATCH' in prompt: result['session_id'] = 'wrong'
if 'TEST_DENIED' in prompt: result['permission_denials'] = [{'tool_name': 'Bash'}]
if 'TEST_ERROR' in prompt: result.update(is_error=True, subtype='error_max_turns')
if 'TEST_NO_REPORT' in prompt: del result['structured_output']
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
        self.assertTrue((run / 'report.md').exists())
        self.assertFalse((self.workspace / 'INJECTED').exists())
        args = json.loads((self.workspace / 'fake-args.json').read_text())
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

    def test_blocked_and_denials_are_not_success(self):
        for mode in ('BLOCKED', 'DENIED'):
            result, run = self.run_phase('TEST_' + mode)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(self.metadata(run)['status'], 'blocked')
            self.assertEqual(json.loads((run / 'report.json').read_text())['status'], 'blocked')

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
