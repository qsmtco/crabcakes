from utils.escaping import escape_for_pango
from utils.markdown import _parse_code_span, _collect_code_spans

# Inline-code-with-literal-tt + fenced block
escaped = "Specifically, `<tt>` tags and:\n\n```bash\nrm file\n```\n\nEnd"
print('Escaped:', repr(escaped))

# Trace _collect_code_spans manually
result = _collect_code_spans(escaped)
print()
print('After _collect_code_spans:', repr(result))