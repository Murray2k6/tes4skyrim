"""Console INI declarations cannot abort later authored configuration writes."""

from script_convert import source_files
from script_convert.converter import ScriptConverter
from script_convert.cross_ref import CrossRefGraph


def test_batch_declarations_do_not_abort_assignments(tmp_path, monkeypatch):
    batch = tmp_path / 'settings.ini'
    batch.write_text('float unused\nset MyQuest.value to 3\n', encoding='utf-8')
    monkeypatch.setattr(source_files, 'source_file', lambda *_: batch)
    source = 'scn BatchCaller\nbegin GameMode\nRunBatchScript "settings.ini"\nend'
    result = ScriptConverter(CrossRefGraph()).convert_standalone('BatchCaller', source, 'Quest')
    assert 'MyQuest.value = 3' in result
    assert 'unused' not in result
