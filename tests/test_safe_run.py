"""The post-command gate restores rejected files without discarding clean edits."""
import subprocess
import sys

from tools.validate import safe_run


def test_reverts_only_rejected_writes(tmp_path, monkeypatch, capsys):
    original = tmp_path / 'existing.py'
    clean = tmp_path / 'clean.py'
    created = tmp_path / 'new.py'
    original.write_bytes(b'preexisting uncommitted bytes\r\n')
    clean.write_bytes(b'before\n')
    monkeypatch.setattr(safe_run.CR, 'repo_files', lambda: sorted(tmp_path.glob('*.py')))
    monkeypatch.setattr(safe_run.CR, 'ROOT', tmp_path)
    monkeypatch.setattr(safe_run, 'shell_argv', lambda command: None)
    monkeypatch.setattr(safe_run.CR, 'gate_file', lambda path: path != clean)

    def child(*args, **kwargs):
        """Simulate one command mixing acceptable and rejected writes."""
        original.write_text('bad rewrite', encoding='utf-8')
        clean.write_text('accepted edit', encoding='utf-8')
        created.write_text('bad new file', encoding='utf-8')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(safe_run.subprocess, 'run', child)
    assert safe_run.main('child') == 2
    assert original.read_bytes() == b'preexisting uncommitted bytes\r\n'
    assert clean.read_text(encoding='utf-8') == 'accepted edit'
    assert not created.exists()
    output = capsys.readouterr().err
    assert 'DID NOT STAND' in output
    assert str(original) in output and str(created) in output


def test_preserves_child_failure_when_changes_pass(tmp_path, monkeypatch):
    path = tmp_path / 'file.py'
    path.write_bytes(b'before')
    monkeypatch.setattr(safe_run.CR, 'repo_files', lambda: [path])
    monkeypatch.setattr(safe_run.CR, 'ROOT', tmp_path)
    monkeypatch.setattr(safe_run.CR, 'gate_file', lambda path: 0)
    monkeypatch.setattr(safe_run, 'shell_argv', lambda command: None)

    def child(*args, **kwargs):
        """A failed command can still leave a valid edit."""
        path.write_bytes(b'accepted')
        return subprocess.CompletedProcess(args, 7)

    monkeypatch.setattr(safe_run.subprocess, 'run', child)
    assert safe_run.main('child') == 7
    assert path.read_bytes() == b'accepted'


def test_real_child_and_whole_file_gate_restore_bytes(tmp_path, monkeypatch):
    """Exercise the real subprocess and rule detector, including existing rule debt."""
    path = tmp_path / 'subject.py'
    original = b'def legacy():\n    return 1\n'
    path.write_bytes(original)
    monkeypatch.setattr(safe_run.CR, 'repo_files', lambda: [path])
    monkeypatch.setattr(safe_run.CR, 'ROOT', tmp_path)
    code = 'from pathlib import Path; Path("subject.py").write_text("def legacy():\\n    return 2\\n")'
    monkeypatch.setattr(safe_run, 'shell_argv', lambda command: [sys.executable, '-c', code])
    assert safe_run.main('child') == 2
    assert path.read_bytes() == original
