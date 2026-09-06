"""Publish source semantics for generated records the runtime cannot infer."""

from pathlib import Path


def write_effect_metadata(output_path, masters):
    from .record_types.magic import runtime_effects, runtime_effect_flags, runtime_effect_actor_values
    output = Path(output_path)
    plugins = list(masters) + [output.name]
    rows = []
    for fid, (code, bound_item) in sorted(runtime_effects.items()):
        if len(code) != 4:
            raise ValueError(f'Invalid source magic-effect code: {code!r}')
        fields = f'EffectCode={int.from_bytes(code.encode("ascii"), "little", signed=True)}'
        if fid in runtime_effect_actor_values:
            fields += f'\tEffectActorValue={runtime_effect_actor_values[fid]}'
        if code in runtime_effect_flags:
            flags = runtime_effect_flags[code]
            fields += f'\tEffectFlags={flags if flags < 0x80000000 else flags - 0x100000000}'
        if bound_item:
            fields += f'\t@BoundItem={plugins[bound_item >> 24]}|{bound_item & 0xFFFFFF:06X}'
        rows.append(f'{plugins[fid >> 24]}\t{fid & 0xFFFFFF:06X}\t12\t-1\t-1\t{fields}\n')
    directory = output.parent / 'SKSE/Plugins/TES4Runtime/effects'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (output.name + '.tsv')).write_text(''.join(rows), encoding='utf-8')
