"""
Deterministic JSON repair for LLM-generated tool-call arguments.

No model calls — purely algorithmic brace/quote balancing.
Handles the most common failure modes of local models (Qwen, Fable, etc.)
so that at minimum a closed JSON object is fed back to the model instead
of crashing the tool execution.

Common LLM JSON errors handled:
- Unclosed strings:   {"key": "value   →  {"key": "value"}
- Unclosed containers: {"a": [1, 2       →  {"a": [1, 2]}
- Trailing commas:     {"a": 1,}         →  {"a": 1}
- Single quotes:       {'a': 1}          →  {"a": 1}
- Smart quotes:        \u201ckey\u201d          →  "key"
- Markdown fences:     ```json ... ```
- Truncated escapes:   {"p": "C:\\       →  {"p": "C:\\\\"}
"""

import json
import re


# ── Public API ────────────────────────────────────────────────────────────────

def repair_json(text: str) -> dict | list:
    """Parse and repair a potentially malformed JSON string.

    Returns the parsed dict/list on success, or an empty dict if
    the string is irreparable or already empty.
    """
    if not isinstance(text, str):
        try:
            return json.loads(json.dumps(text))
        except Exception:
            return {}

    original = text.strip()
    if not original:
        return {}

    # Fast path: already valid JSON
    try:
        return json.loads(original)
    except (json.JSONDecodeError, ValueError):
        pass

    # Apply progressive repairs
    for repair_func in _REPAIR_STEPS:
        repaired = repair_func(original)
        if repaired is None:
            continue
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            continue

    return {}


def try_parse_arguments(raw: str) -> dict:
    """Safely parse tool-call arguments, returning {} on any failure.

    Uses repair_json internally so malformed LLM output is handled.
    """
    if not raw or not isinstance(raw, str):
        return {}
    result = repair_json(raw)
    if isinstance(result, dict):
        return result
    # List-only arguments (e.g. for ed[...]) — wrap gracefully
    if isinstance(result, list):
        return {"_list_arguments": result}
    return {}


# ── Repair steps (applied in order until one succeeds) ───────────────────────

def _strip_markdown_fence(text: str) -> str | None:
    """Remove ```json / ``` fences that models sometimes wrap JSON in."""
    if text.startswith("```"):
        text = re.sub(r'^```\w*\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        return text.strip()
    return None


def _fix_smart_quotes(text: str) -> str | None:
    """Replace Unicode smart quotes with ASCII quotes."""
    fixed = text
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')  # " "
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")  # ' '
    if fixed != text:
        return fixed
    return None


def _remove_trailing_commas(text: str) -> str | None:
    """Remove commas immediately before } or ]."""
    fixed = re.sub(r',(\s*[}\]])', r'\1', text)
    if fixed != text:
        return fixed
    return None


def _fix_single_to_double_quotes(text: str) -> str | None:
    """Convert Python-style single-quoted dict to double-quoted JSON.

    Only attempts this when the string starts with { or [ and
    contains single-quoted keys or values. Does NOT blindly replace
    every single quote (apostrophes in values must survive).
    """
    if not text.startswith(('{', '[')):
        return None
    if "'" not in text:
        return None

    # Strategy: walk the string character by character, flipping
    # single-quote ↔ double-quote behaviour.  Outside strings the
    # only single-quote usage is Python dict keys/values.
    result: list[str] = []
    i = 0
    in_dq = False   # inside "..."  string
    in_sq = False   # inside '...'  string
    escaped = False

    while i < len(text):
        ch = text[i]

        if escaped:
            result.append(ch)
            escaped = False
            i += 1
            continue

        if ch == '\\' and (in_dq or in_sq):
            result.append(ch)
            escaped = True
            i += 1
            continue

        if ch == '"' and not in_sq:
            in_dq = not in_dq
            result.append(ch)
        elif ch == "'" and not in_dq:
            # Single quotes outside double-quoted strings become double quotes
            in_sq = not in_sq
            result.append('"')
        else:
            result.append(ch)

        i += 1

    return ''.join(result)


def _balance(text: str) -> str | None:
    """Close unclosed strings, then unclosed brackets/braces.

    This is the core repair — it scans once and appends the minimal
    set of closing characters needed to produce balanced JSON.
    """
    result: list[str] = []
    openers: list[str] = []   # stack of '{', '[', '"'
    in_string = False
    escaped = False

    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            continue

        if ch == '\\' and in_string:
            result.append(ch)
            escaped = True
            continue

        if ch == '"':
            if not in_string:
                in_string = True
                openers.append('"')
            else:
                in_string = False
                _pop_opener(openers)
            result.append(ch)
            continue

        if in_string:
            result.append(ch)
            continue

        # Outside strings
        if ch in '{[':
            result.append(ch)
            openers.append(ch)
        elif ch in '}]':
            _close_until(openers, '{' if ch == '}' else '[', result)
            result.append(ch)
        else:
            result.append(ch)

    # Close anything still open at end of input
    if in_string:
        result.append('"')
        _pop_opener(openers)
        in_string = False

    _close_all(openers, result)

    if result != list(text):
        return ''.join(result)
    return None


def _pop_opener(openers: list[str]) -> None:
    """Remove the string opener from the top of the stack."""
    if openers and openers[-1] == '"':
        openers.pop()


def _close_until(openers: list[str], target: str, result: list[str]) -> None:
    """Close any open strings/brackets until the target opener is on top,
    then pop the target opener.  Used when a structural closer ('}'/']')
    appears in the input."""
    while openers:
        top = openers[-1]
        if top == target:
            openers.pop()
            return
        if top == '"':
            result.append('"')
            openers.pop()
        elif top == '[':
            # Input had '}' but a '[' is still open — close it first
            result.append(']')
            openers.pop()
        elif top == '{' and target == ']':
            # Input had ']' but a '{' is still open — close it first
            result.append('}')
            openers.pop()
        else:
            # Top is '{' and target is '}' — handled by the 'if' above.
            # Any other combination means the input is structurally broken;
            # stop here to avoid infinite loops.
            break


def _close_all(openers: list[str], result: list[str]) -> None:
    """Append closing characters for every remaining opener."""
    closing = {'{': '}', '[': ']'}
    for opener in reversed(openers):
        if opener == '"':
            result.append('"')
        elif opener in closing:
            result.append(closing[opener])


# ── Ordered repair steps ─────────────────────────────────────────────────────

_REPAIR_STEPS = [
    _strip_markdown_fence,
    _fix_smart_quotes,
    _remove_trailing_commas,
    _fix_single_to_double_quotes,
    _balance,
    # Composite: trailing commas THEN balance (both common together)
    lambda t: _balance(_remove_trailing_commas(t) or t) if _remove_trailing_commas(t) else None,
    lambda t: _balance(_fix_single_to_double_quotes(t) or t) if _fix_single_to_double_quotes(t) else None,
]
