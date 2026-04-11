"""
Tests for ui/handlers/prompts_handler.py
"""
import os
import pytest


class TestSearch:
    def test_empty_query_returns_all_prompts(self, tmp_prompts_dir):
        """Empty search query must not filter anything."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)
        h._prompts = [
            {'name': 'alpha', 'filepath': '/p/alpha.md', 'content': '', 'lines': 1, 'size': 10},
            {'name': 'beta', 'filepath': '/p/beta.md', 'content': '', 'lines': 1, 'size': 10},
        ]
        result = h.search('')
        assert len(result) == 2

    def test_query_filters_correctly(self, tmp_prompts_dir):
        """Search must be case-insensitive substring match."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)
        h._prompts = [
            {'name': 'alpha', 'filepath': '/p/alpha.md', 'content': '', 'lines': 1, 'size': 10},
            {'name': 'beta', 'filepath': '/p/beta.md', 'content': '', 'lines': 1, 'size': 10},
            {'name': 'Alphabet', 'filepath': '/p/alphabet.md', 'content': '', 'lines': 1, 'size': 10},
        ]
        result = h.search('alp')
        assert len(result) == 2
        names = [r['name'] for r in result]
        assert 'alpha' in names
        assert 'Alphabet' in names

    def test_favorites_sort_to_top(self, tmp_prompts_dir):
        """Favorited prompts must appear before non-favorites."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)
        h._prompts = [
            {'name': 'alpha', 'filepath': '/p/alpha.md', 'content': '', 'lines': 1, 'size': 10},
            {'name': 'beta', 'filepath': '/p/beta.md', 'content': '', 'lines': 1, 'size': 10},
        ]
        h._favorites = {'/p/beta.md'}
        result = h.search('')
        assert result[0]['name'] == 'beta'
        assert result[1]['name'] == 'alpha'

    def test_load_prompts_with_real_files(self, tmp_prompts_dir):
        """load_prompts reads from _get_prompts_dir and returns metadata."""
        from ui.handlers.prompts_handler import PromptsHandler
        import ui.handlers.prompts_handler as ph_mod
        # Patch _get_prompts_dir to return our temp directory
        old_get = ph_mod.PromptsHandler._get_prompts_dir
        ph_mod.PromptsHandler._get_prompts_dir = lambda self: str(tmp_prompts_dir)
        try:
            h = PromptsHandler(on_refresh_ui=None)
            h._favorites = set()
            prompts = h.load_prompts()
            names = [p['name'] for p in prompts]
            assert 'sample' in names
            assert 'example' in names
            for p in prompts:
                assert p['lines'] > 0
                assert p['size'] > 0
                assert p['is_favorite'] is False
        finally:
            ph_mod.PromptsHandler._get_prompts_dir = old_get


class TestRecordUsage:
    def test_record_usage_stores_timestamp(self, tmp_prompts_dir):
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler()
        h.record_usage('/p/alpha.md')
        assert '/p/alpha.md' in h._last_used
        assert h._last_used['/p/alpha.md'] > 0

    def test_get_last_used_str_just_now(self, tmp_prompts_dir):
        import time
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler()
        h._last_used['/p/alpha.md'] = time.time()
        result = h.get_last_used_str('/p/alpha.md')
        assert result == 'just now'

    def test_get_last_used_str_unknown_returns_empty(self, tmp_prompts_dir):
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler()
        assert h.get_last_used_str('/unknown.md') == ''


class TestGetPromptContent:
    def test_get_prompt_content_reads_file(self, tmp_prompts_dir):
        from ui.handlers.prompts_handler import PromptsHandler
        p = tmp_prompts_dir / 'test.md'
        p.write_text('# Test Content\nHello world')
        h = PromptsHandler()
        name, content = h.get_prompt_content(str(p))
        assert name == 'test.md'
        assert content == '# Test Content\nHello world'

    def test_get_prompt_content_missing_file_returns_empty(self, tmp_prompts_dir):
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler()
        _, content = h.get_prompt_content('/nonexistent.md')
        assert content == ''
