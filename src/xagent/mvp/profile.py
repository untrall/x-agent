"""One evidence-based public profile for both the name card and policy context."""
from .scenario import coerce_fact


def profile_view(profile: dict, scenario: dict, facts: dict) -> dict:
    description = str(profile.get('description') or '、'.join(str(t) for t in profile.get('tags', [])) or '个人简介待补充')
    confirmed = {}
    unknown = []
    details = []
    for field in profile.get('public_fields', []):
        spec = scenario.get('fields', {}).get(field)
        if spec is None:
            continue
        label = spec.get('label') or field
        try:
            value = coerce_fact(field, facts.get(field), scenario)
        except ValueError:
            unknown.append(field)
            details.append(f'{label}：待确认')
            continue
        confirmed[field] = value
        display = ('是' if value else '否') if isinstance(value, bool) else str(value)
        details.append(f'{label}: {display}')
    return {'description': description, 'facts': confirmed, 'unknown_fields': unknown,
            'summary': description + ('\n' + ' · '.join(details) if details else '')}
