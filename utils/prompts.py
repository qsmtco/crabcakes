# utils/prompts.py
# Loads .md prompt files from the prompts/ directory

import os

PROMPTS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def load_prompts() -> list[tuple[str, str]]:
    """
    Load all .md files from the prompts/ directory.
    Returns [(display_name, file_content)] — filename without .md as name.
    """
    if not os.path.isdir(PROMPTS_DIR):
        return []
    result: list[tuple[str, str]] = []
    for filename in sorted(os.listdir(PROMPTS_DIR)):
        if not filename.endswith(".md"):
            continue
        display_name: str = filename[:-3]
        file_path: str = os.path.join(PROMPTS_DIR, filename)
        with open(file_path, encoding="utf-8") as f:
            content: str = f.read()
        result.append((display_name, content))
    return result
