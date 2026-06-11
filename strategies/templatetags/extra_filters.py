import json as _json

from django import template

register = template.Library()


@register.filter
def split(value, sep=","):
    """Split a string by separator: {{ "a,b,c"|split:"," }}"""
    return str(value).split(sep)


@register.filter
def mul(value, arg):
    """Multiply: {{ 0.75|mul:100 }} → 75.0"""
    try:
        return float(value) * float(arg)
    except (TypeError, ValueError):
        return 0


@register.filter
def div(value, arg):
    """Divide: {{ 75|div:100 }} → 0.75  (returns 0 on div/0)"""
    try:
        d = float(arg)
        if d == 0:
            return 0
        return float(value) / d
    except (TypeError, ValueError):
        return 0


@register.filter
def pprint_json(value):
    """Pretty-print a JSON value or dict/list."""
    try:
        if isinstance(value, str):
            parsed = _json.loads(value)
        else:
            parsed = value
        return _json.dumps(parsed, indent=2, ensure_ascii=False)
    except Exception:
        return str(value)
