"""Select presentation language from the operating system's display language."""
import ctypes
import locale
import os
import sys


def normalize_language(language):
    language = str(language or '').replace('_', '-').lower()
    return 'zh-CN' if language.split('-')[0] == 'zh' else 'en'


def system_language():
    # Resolution order: FM27_UI_LANGUAGE, then the Windows display language, then the POSIX locale.
    language = os.environ.get('FM27_UI_LANGUAGE', '')
    if not language and sys.platform == 'win32':
        try:
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                language = locale.windows_locale.get(
                    ctypes.windll.kernel32.GetUserDefaultUILanguage(), buffer.value)
        except (AttributeError, OSError):
            pass
    if not language:
        language = locale.getlocale()[0] or 'en'
    return {'language': normalize_language(language), 'system_language': language,
            'supported': ['zh-CN', 'en'], 'source': 'system'}
