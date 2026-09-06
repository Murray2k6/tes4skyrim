"""Keep authored effect indices for OBSE queries after effect translation."""


def effect_traits(record):
    count = int(record.get('EffectCount', '0'))
    traits = {'EffectCount': count}
    for index in range(count):
        prefix = f'Effect[{index}].'
        for field in ('Magnitude', 'Area', 'Duration', 'ActorValue'):
            traits[f'Effect{index}{field}'] = int(record.get(prefix + field, '0'))
        traits[f'Effect{index}Range'] = {'Self': 0, 'Touch': 1, 'Target': 2}.get(
            record.get(prefix + 'Type'), 0)
        code = record.get(prefix + 'EFID', '')
        traits[f'Effect{index}Code'] = int.from_bytes(code.encode('ascii'), 'little', signed=True)
    return traits
