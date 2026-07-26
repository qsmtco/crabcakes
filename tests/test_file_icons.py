# tests/test_file_icons.py
# Unit tests for utils/file_icons.py

import pytest
from utils.file_icons import (
    FileIcon,
    get_icon_for_path,
    guess_mime,
    _EXTENSION_MAP,
    _DEFAULT_FILE,
    _DEFAULT_DIR,
)


class TestFileIcon:
    def test_dataclass_creation(self):
        icon = FileIcon("test-icon", "test-class")
        assert icon.icon_name == "test-icon"
        assert icon.color_class == "test-class"

    def test_dataclass_frozen(self):
        icon = FileIcon("test", "test")
        with pytest.raises(AttributeError):
            icon.icon_name = "other"

    def test_default_file_icon(self):
        assert _DEFAULT_FILE.icon_name == "text-x-generic-symbolic"
        assert _DEFAULT_FILE.color_class == "file-icon-default"

    def test_default_dir_icon(self):
        assert _DEFAULT_DIR.icon_name == "folder-symbolic"
        assert _DEFAULT_DIR.color_class == "file-icon-folder"


class TestGetIconForPath:
    def test_directory_returns_default_dir(self):
        result = get_icon_for_path("/any/path", True)
        assert result == _DEFAULT_DIR

    def test_empty_path_returns_default_file(self):
        result = get_icon_for_path("", False)
        assert result == _DEFAULT_FILE

    def test_python_file(self):
        result = get_icon_for_path("test.py", False)
        assert result.icon_name == "text-x-python-symbolic"
        assert result.color_class == "file-icon-python"

    def test_python_variants(self):
        for ext in [".py", ".pyi", ".pyw", ".ipynb"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name in ("text-x-python-symbolic", "text-x-ipynb-symbolic")
            assert result.color_class == "file-icon-python"

    def test_javascript_typescript(self):
        for ext in [".js", ".jsx", ".mjs", ".cjs"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "text-x-javascript-symbolic"
            assert result.color_class == "file-icon-js"

        for ext in [".ts", ".tsx"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "text-x-typescript-symbolic"
            assert result.color_class == "file-icon-ts"

    def test_json_yaml_toml(self):
        for ext in [".json", ".jsonc"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "application-json-symbolic"
            assert result.color_class == "file-icon-json"

        for ext in [".yaml", ".yml"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "application-x-yaml-symbolic"
            assert result.color_class == "file-icon-yaml"

        result = get_icon_for_path("file.toml", False)
        assert result.icon_name == "application-x-toml-symbolic"
        assert result.color_class == "file-icon-yaml"

    def test_markdown(self):
        for ext in [".md", ".markdown", ".rst"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name in ("text-x-markdown-symbolic", "text-x-rst-symbolic")
            assert result.color_class == "file-icon-md"

    def test_html_css(self):
        for ext in [".html", ".htm"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "text-html-symbolic"
            assert result.color_class == "file-icon-html"

        for ext in [".css", ".scss", ".sass", ".less"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "text-css-symbolic"
            assert result.color_class == "file-icon-css"

    def test_rust(self):
        result = get_icon_for_path("file.rs", False)
        assert result.icon_name == "text-x-rust-symbolic"
        assert result.color_class == "file-icon-rust"

    def test_go(self):
        result = get_icon_for_path("file.go", False)
        assert result.icon_name == "text-x-go-symbolic"
        assert result.color_class == "file-icon-go"

    def test_java_kotlin(self):
        result = get_icon_for_path("file.java", False)
        assert result.icon_name == "text-x-java-symbolic"
        assert result.color_class == "file-icon-java"

        result = get_icon_for_path("file.kt", False)
        assert result.icon_name == "text-x-kotlin-symbolic"
        assert result.color_class == "file-icon-kotlin"

    def test_c_cpp(self):
        for ext in [".c", ".h"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.color_class == "file-icon-cpp"

        for ext in [".cpp", ".cc", ".cxx", ".hpp", ".hxx"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.color_class == "file-icon-cpp"

    def test_shell(self):
        for ext in [".sh", ".bash", ".zsh", ".fish"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.icon_name == "text-x-shellscript-symbolic"
            assert result.color_class == "file-icon-sh"

        result = get_icon_for_path("file.ps1", False)
        assert result.icon_name == "text-x-powershell-symbolic"
        assert result.color_class == "file-icon-sh"

    def test_images(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.color_class in ("file-icon-png", "file-icon-jpg", "file-icon-gif")

    def test_pdf(self):
        result = get_icon_for_path("file.pdf", False)
        assert result.icon_name == "application-pdf-symbolic"
        assert result.color_class == "file-icon-pdf"

    def test_archives(self):
        for ext in [".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.color_class == "file-icon-zip"

    def test_binaries(self):
        for ext in [".exe", ".dll", ".so", ".dylib"]:
            result = get_icon_for_path(f"file{ext}", False)
            assert result.color_class == "file-icon-binary"

    def test_compound_extensions(self):
        # .tar.gz should match .gz (longest match first)
        result = get_icon_for_path("archive.tar.gz", False)
        assert result.color_class == "file-icon-zip"

    def test_case_insensitive(self):
        result = get_icon_for_path("FILE.PY", False)
        assert result.icon_name == "text-x-python-symbolic"

        result = get_icon_for_path("Test.Js", False)
        assert result.icon_name == "text-x-javascript-symbolic"

    def test_mime_fallback(self):
        # No extension, but mime type provided
        result = get_icon_for_path("README", False, mime_type="text/markdown")
        assert result.icon_name == "text-x-markdown-symbolic"
        assert result.color_class == "file-icon-md"

    def test_unknown_extension_returns_default(self):
        result = get_icon_for_path("file.xyz123", False)
        assert result == _DEFAULT_FILE

    def test_dockerfile(self):
        # Dockerfile (case-insensitive)
        for name in ["Dockerfile", "dockerfile", "DOCKERFILE"]:
            result = get_icon_for_path(name, False)
            assert result.icon_name == "text-x-dockerfile-symbolic"
            assert result.color_class == "file-icon-docker"

    def test_git_files(self):
        for name in [".gitignore", ".gitattributes"]:
            result = get_icon_for_path(name, False)
            assert result.color_class == "file-icon-git"

    def test_config_files(self):
        for name in [".env", ".ini", ".cfg", ".conf"]:
            result = get_icon_for_path(name, False)
            assert result.color_class == "file-icon-config"

    def test_log_lock(self):
        result = get_icon_for_path("app.log", False)
        assert result.icon_name == "text-x-log-symbolic"
        assert result.color_class == "file-icon-log"

        result = get_icon_for_path("yarn.lock", False)
        assert result.color_class == "file-icon-lock"


class TestGuessMime:
    def test_known_extensions(self):
        assert guess_mime("test.py") == "text/x-python"
        assert guess_mime("test.json") == "application/json"
        assert guess_mime("test.md") == "text/markdown"
        assert guess_mime("test.png") == "image/png"

    def test_unknown_extension(self):
        # mimetypes may or may not know this
        result = guess_mime("file.unknown")
        assert isinstance(result, str)


class TestExtensionMapCompleteness:
    def test_all_extensions_have_valid_icons(self):
        for ext, icon in _EXTENSION_MAP.items():
            assert isinstance(icon, FileIcon)
            assert isinstance(icon.icon_name, str) and icon.icon_name
            assert isinstance(icon.color_class, str) and icon.color_class

    def test_no_duplicate_extensions(self):
        # Just verify dict keys are unique (they are by definition)
        assert len(_EXTENSION_MAP) == len(set(_EXTENSION_MAP.keys()))

    def test_all_color_classes_start_with_prefix(self):
        for icon in _EXTENSION_MAP.values():
            assert icon.color_class.startswith("file-icon-")