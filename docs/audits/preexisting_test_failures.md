# Pre-existing test failures at `f6bbdf6`

**50 tests fail on a clean checkout of `master`**, before any `asset_convert/`
reorganization work. Measured by creating a detached worktree at HEAD and
running the full suite there:

```bash
git worktree add --detach <tmp> HEAD
cd <tmp> && python -m pytest tests/ -q
# 50 failed, 2205 passed, 366 skipped
```

They cluster into five suites and four independent causes. **None are caused by
the `asset_convert/` subfolder move** — the same worktree run reproduces every
one of them without it.

## `tests/test_script_converter.py` — 42 failures

Two distinct causes, both a renamed method the tests still call:

| Cause | Count | Symptom |
|---|---:|---|
| `ScriptConverter._emit_function` no longer exists | ~36 | `AttributeError: 'ScriptConverter' object has no attribute '_emit_function'` |
| `IsActionRef` lost its `akActionRef` binding | 4 | `assert 'akActionRef' in 'Self == Game.GetPlayer()'` |

The `_emit_function` group spans `TestArgParsing`, `TestFunctionConversion`,
`TestChargenMenus`, `TestSayTimerConversion`, `TestSingletonFixes`,
`TestTypeOf`, `TestEarlyReturnKeepsPolling`, `TestLocalVariableShadowsPlayer`
and `TestPlayerControlsShadow` — one refactor, many call sites. The tests were
not updated with the rename.

The `IsActionRef` pair (`test_isactionref_eq_0`, `test_isactionref_eq_1`,
`test_isactionref`, `test_getactionref`) is a separate behavioural change:
the converter now emits `Self == Game.GetPlayer()` where the test expects an
`akActionRef` parameter reference.

## `tests/test_version_upgrade.py` — 2 failures

`gui.STEPS` and `version.STEP_KEYS` have drifted apart: `gui.py` declares a
`convert_ui` step that `version.py` does not list.

- `test_step_keys_match_the_gui_step_table` — `Left contains one more item: 'convert_ui'`
- `test_every_global_action_is_a_global_step`

## `tests/test_audio_converter.py` — 3 failures — **FIXED in passing**

`test_organize_voice_files_{basic,uses_voice_map,prunes_renamed_leftovers}`.
These assert on `organize_voice_files`, which was reached through a private
name. They pass once the name is promoted, so the reorganization work fixes
them incidentally.

## `tests/test_hair_conversion.py` — 2 failures — **FIXED in passing**

`test_race_hair_is_fitted_to_its_own_heads` (`AssertionError: no race hair
checked`) and `test_head_fit_keeps_the_mesh_intact_and_unsized`
(`too few meshes checked`, `assert 0 >= 3`). Both are guard assertions firing
because the fixture found zero inputs, not because the conversion is wrong.

## `tests/test_plugin_path_resolution.py` — 1 failure

`test_no_module_joins_a_plugin_name_onto_a_root` —
`Failed: A plugin name is joined onto an export/output root.` A lint-style
invariant test over the source; some module concatenates a plugin name onto a
root path where it should use the layout resolver.

## Also broken, but deselected rather than counted

`tests/test_ck_load_and_render_invariants.py::test_ck_load_gate` parametrises
over `tools/cell_grid_check.py` and `tools/esm_group_anchors.py`. Neither file
exists anywhere in the tree — `tools/` is organised into category subfolders,
and these two were never moved or were deleted. The test fails with
`[Errno 2] No such file or directory`, not an assertion.
