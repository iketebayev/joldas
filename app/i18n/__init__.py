"""Три языка интерфейса. Ключ ищется в выбранном языке, потом в русском."""
import json
from pathlib import Path

from ..config import UI_LANGS

_DIR = Path(__file__).parent
_STRINGS: dict[str, dict[str, str]] = {
    lang: json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8")) for lang in UI_LANGS
}


def t(lang: str, key: str, /, **kw) -> str:
    s = _STRINGS.get(lang, {}).get(key) or _STRINGS["ru"].get(key) or key
    return s.format(**kw) if kw else s


def missing_keys() -> dict[str, list[str]]:
    """Для проверки: какие ключи есть в русском, но не переведены."""
    base = set(_STRINGS["ru"])
    return {lang: sorted(base - set(_STRINGS[lang])) for lang in UI_LANGS if lang != "ru"}


def pick_lang(cookie: str | None, accept_language: str | None) -> str:
    if cookie in UI_LANGS:
        return cookie
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in UI_LANGS:
            return code
    return "ru"
