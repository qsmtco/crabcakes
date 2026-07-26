# utils/file_icons.py
# File type icon registry — pure Python, no GTK imports.
# Returns GTK icon names and CSS color classes for file tree display.

from dataclasses import dataclass
import mimetypes


@dataclass(frozen=True)
class FileIcon:
    """Icon metadata for a file type."""
    icon_name: str      # GTK icon name (e.g., "text-x-python-symbolic")
    color_class: str    # CSS class for color (e.g., "file-icon-python")


# Default icons
_DEFAULT_FILE = FileIcon("text-x-generic-symbolic", "file-icon-default")
_DEFAULT_DIR = FileIcon("folder-symbolic", "file-icon-folder")


# Extension -> FileIcon mapping (~60 entries)
_EXTENSION_MAP: dict[str, FileIcon] = {
    # Python
    ".py": FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".pyi": FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".pyw": FileIcon("text-x-python-symbolic", "file-icon-python"),
    ".ipynb": FileIcon("text-x-ipynb-symbolic", "file-icon-python"),
    # JavaScript / TypeScript
    ".js": FileIcon("text-x-javascript-symbolic", "file-icon-js"),
    ".jsx": FileIcon("text-x-javascript-symbolic", "file-icon-js"),
    ".mjs": FileIcon("text-x-javascript-symbolic", "file-icon-js"),
    ".cjs": FileIcon("text-x-javascript-symbolic", "file-icon-js"),
    ".ts": FileIcon("text-x-typescript-symbolic", "file-icon-ts"),
    ".tsx": FileIcon("text-x-typescript-symbolic", "file-icon-ts"),
    # JSON / YAML / TOML
    ".json": FileIcon("application-json-symbolic", "file-icon-json"),
    ".jsonc": FileIcon("application-json-symbolic", "file-icon-json"),
    ".yaml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    ".yml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    ".toml": FileIcon("application-x-toml-symbolic", "file-icon-yaml"),
    # Markdown / Text
    ".md": FileIcon("text-x-markdown-symbolic", "file-icon-md"),
    ".markdown": FileIcon("text-x-markdown-symbolic", "file-icon-md"),
    ".txt": FileIcon("text-x-generic-symbolic", "file-icon-md"),
    ".rst": FileIcon("text-x-rst-symbolic", "file-icon-md"),
    # HTML / CSS / SCSS
    ".html": FileIcon("text-html-symbolic", "file-icon-html"),
    ".htm": FileIcon("text-html-symbolic", "file-icon-html"),
    ".css": FileIcon("text-css-symbolic", "file-icon-css"),
    ".scss": FileIcon("text-css-symbolic", "file-icon-css"),
    ".sass": FileIcon("text-css-symbolic", "file-icon-css"),
    ".less": FileIcon("text-css-symbolic", "file-icon-css"),
    # Rust
    ".rs": FileIcon("text-x-rust-symbolic", "file-icon-rust"),
    ".toml": FileIcon("application-x-toml-symbolic", "file-icon-yaml"),
    # Go
    ".go": FileIcon("text-x-go-symbolic", "file-icon-go"),
    # Java / Kotlin
    ".java": FileIcon("text-x-java-symbolic", "file-icon-java"),
    ".kt": FileIcon("text-x-kotlin-symbolic", "file-icon-kotlin"),
    ".kts": FileIcon("text-x-kotlin-symbolic", "file-icon-kotlin"),
    # C / C++
    ".c": FileIcon("text-x-csrc-symbolic", "file-icon-cpp"),
    ".h": FileIcon("text-x-chdr-symbolic", "file-icon-cpp"),
    ".cpp": FileIcon("text-x-c++src-symbolic", "file-icon-cpp"),
    ".cc": FileIcon("text-x-c++src-symbolic", "file-icon-cpp"),
    ".cxx": FileIcon("text-x-c++src-symbolic", "file-icon-cpp"),
    ".hpp": FileIcon("text-x-c++hdr-symbolic", "file-icon-cpp"),
    ".hxx": FileIcon("text-x-c++hdr-symbolic", "file-icon-cpp"),
    # Shell
    ".sh": FileIcon("text-x-shellscript-symbolic", "file-icon-sh"),
    ".bash": FileIcon("text-x-shellscript-symbolic", "file-icon-sh"),
    ".zsh": FileIcon("text-x-shellscript-symbolic", "file-icon-sh"),
    ".fish": FileIcon("text-x-shellscript-symbolic", "file-icon-sh"),
    ".ps1": FileIcon("text-x-powershell-symbolic", "file-icon-sh"),
    # Ruby / PHP / Swift / Dart / Lua / Perl / R
    ".rb": FileIcon("text-x-ruby-symbolic", "file-icon-ruby"),
    ".php": FileIcon("text-x-php-symbolic", "file-icon-php"),
    ".swift": FileIcon("text-x-swift-symbolic", "file-icon-swift"),
    ".dart": FileIcon("text-x-dart-symbolic", "file-icon-dart"),
    ".lua": FileIcon("text-x-lua-symbolic", "file-icon-lua"),
    ".pl": FileIcon("text-x-perl-symbolic", "file-icon-perl"),
    ".pm": FileIcon("text-x-perl-symbolic", "file-icon-perl"),
    ".r": FileIcon("text-x-r-symbolic", "file-icon-r"),
    # SQL
    ".sql": FileIcon("application-x-sql-symbolic", "file-icon-sql"),
    # XML / SVG
    ".xml": FileIcon("application-xml-symbolic", "file-icon-xml"),
    ".svg": FileIcon("image-svg+xml-symbolic", "file-icon-xml"),
    # Images
    ".png": FileIcon("image-png-symbolic", "file-icon-png"),
    ".jpg": FileIcon("image-jpeg-symbolic", "file-icon-jpg"),
    ".jpeg": FileIcon("image-jpeg-symbolic", "file-icon-jpg"),
    ".gif": FileIcon("image-gif-symbolic", "file-icon-gif"),
    ".webp": FileIcon("image-webp-symbolic", "file-icon-png"),
    ".ico": FileIcon("image-x-icon-symbolic", "file-icon-png"),
    # PDF
    ".pdf": FileIcon("application-pdf-symbolic", "file-icon-pdf"),
    # Archives
    ".zip": FileIcon("application-zip-symbolic", "file-icon-zip"),
    ".tar": FileIcon("application-x-tar-symbolic", "file-icon-zip"),
    ".gz": FileIcon("application-gzip-symbolic", "file-icon-zip"),
    ".bz2": FileIcon("application-x-bzip2-symbolic", "file-icon-zip"),
    ".xz": FileIcon("application-x-xz-symbolic", "file-icon-zip"),
    ".7z": FileIcon("application-x-7z-compressed-symbolic", "file-icon-zip"),
    ".rar": FileIcon("application-x-rar-symbolic", "file-icon-zip"),
    # Binaries
    ".exe": FileIcon("application-x-executable-symbolic", "file-icon-binary"),
    ".dll": FileIcon("application-x-sharedlib-symbolic", "file-icon-binary"),
    ".so": FileIcon("application-x-sharedlib-symbolic", "file-icon-binary"),
    ".dylib": FileIcon("application-x-sharedlib-symbolic", "file-icon-binary"),
    # Java bytecode / Android
    ".class": FileIcon("application-x-java-archive-symbolic", "file-icon-binary"),
    ".jar": FileIcon("application-x-java-archive-symbolic", "file-icon-binary"),
    ".war": FileIcon("application-x-java-archive-symbolic", "file-icon-binary"),
    ".ear": FileIcon("application-x-java-archive-symbolic", "file-icon-binary"),
    # Docker
    "Dockerfile": FileIcon("text-x-dockerfile-symbolic", "file-icon-docker"),
    ".dockerignore": FileIcon("text-x-generic-symbolic", "file-icon-docker"),
    # Git
    ".gitignore": FileIcon("text-x-generic-symbolic", "file-icon-git"),
    ".gitattributes": FileIcon("text-x-generic-symbolic", "file-icon-git"),
    # Config / Env
    ".env": FileIcon("text-x-generic-symbolic", "file-icon-config"),
    ".ini": FileIcon("text-x-generic-symbolic", "file-icon-config"),
    ".cfg": FileIcon("text-x-generic-symbolic", "file-icon-config"),
    ".conf": FileIcon("text-x-generic-symbolic", "file-icon-config"),
    # Logs / Lock files
    ".log": FileIcon("text-x-log-symbolic", "file-icon-log"),
    ".lock": FileIcon("text-x-generic-symbolic", "file-icon-lock"),
}

# MIME type -> FileIcon fallback
_MIME_MAP: dict[str, FileIcon] = {
    "text/plain": FileIcon("text-x-generic-symbolic", "file-icon-default"),
    "text/x-python": FileIcon("text-x-python-symbolic", "file-icon-python"),
    "text/x-script.python": FileIcon("text-x-python-symbolic", "file-icon-python"),
    "application/json": FileIcon("application-json-symbolic", "file-icon-json"),
    "application/x-yaml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    "text/x-yaml": FileIcon("application-x-yaml-symbolic", "file-icon-yaml"),
    "text/markdown": FileIcon("text-x-markdown-symbolic", "file-icon-md"),
    "text/html": FileIcon("text-html-symbolic", "file-icon-html"),
    "text/css": FileIcon("text-css-symbolic", "file-icon-css"),
    "text/x-rust": FileIcon("text-x-rust-symbolic", "file-icon-rust"),
    "text/x-go": FileIcon("text-x-go-symbolic", "file-icon-go"),
    "text/x-java-source": FileIcon("text-x-java-symbolic", "file-icon-java"),
    "text/x-csrc": FileIcon("text-x-csrc-symbolic", "file-icon-cpp"),
    "text/x-c++src": FileIcon("text-x-c++src-symbolic", "file-icon-cpp"),
    "text/x-shellscript": FileIcon("text-x-shellscript-symbolic", "file-icon-sh"),
    "application/pdf": FileIcon("application-pdf-symbolic", "file-icon-pdf"),
    "image/png": FileIcon("image-png-symbolic", "file-icon-png"),
    "image/jpeg": FileIcon("image-jpeg-symbolic", "file-icon-jpg"),
    "image/gif": FileIcon("image-gif-symbolic", "file-icon-gif"),
    "image/svg+xml": FileIcon("image-svg+xml-symbolic", "file-icon-xml"),
    "application/zip": FileIcon("application-zip-symbolic", "file-icon-zip"),
    "application/x-tar": FileIcon("application-x-tar-symbolic", "file-icon-zip"),
    "application/gzip": FileIcon("application-gzip-symbolic", "file-icon-zip"),
    "application/x-bzip2": FileIcon("application-x-bzip2-symbolic", "file-icon-zip"),
    "application/x-7z-compressed": FileIcon("application-x-7z-compressed-symbolic", "file-icon-zip"),
    "application/x-rar-compressed": FileIcon("application-x-rar-symbolic", "file-icon-zip"),
    "application/x-sharedlib": FileIcon("application-x-sharedlib-symbolic", "file-icon-binary"),
    "application/x-executable": FileIcon("application-x-executable-symbolic", "file-icon-binary"),
    "application/java-archive": FileIcon("application-x-java-archive-symbolic", "file-icon-binary"),
}


def get_icon_for_path(path: str, is_dir: bool, mime_type: str | None = None) -> FileIcon:
    """Return FileIcon for a path. Priority: explicit extension → MIME → default.

    If path is empty or has no extension, falls through to MIME → default.
    is_dir always returns _DEFAULT_DIR.
    """
    if is_dir:
        return _DEFAULT_DIR

    # Extension match (longest first — handles .tar.gz → .gz, .pyi → .pyi)
    path_lower = path.lower()
    for ext in sorted(_EXTENSION_MAP.keys(), key=len, reverse=True):
        if path_lower.endswith(ext):
            return _EXTENSION_MAP[ext]

    # MIME fallback
    if mime_type and mime_type in _MIME_MAP:
        return _MIME_MAP[mime_type]

    return _DEFAULT_FILE


def guess_mime(path: str) -> str:
    """Guess MIME type from file path."""
    mime, _ = mimetypes.guess_type(path)
    return mime or ""