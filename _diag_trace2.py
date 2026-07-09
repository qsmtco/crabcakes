import sys
sys.path.insert(0, '/home/q/projects/crabcakes')
from utils.escaping import escape_for_pango
import utils.markdown as M

escaped = "Specifically, `<tt>` tags and:\n\n```bash\nrm file\n```\n\nEnd"
print('Escaped:', repr(escaped))

# Run format_markdown directly and trace what happens
import re
from utils.markdown import format_markdown
formatted = format_markdown(escaped)
print('Formatted:', repr(formatted))

# Let's manually extract function via code object
print()
print('Function definitions:')
for name in dir(M):
    if 'code' in name.lower() or 'parse' in name.lower():
        print(' ', name)