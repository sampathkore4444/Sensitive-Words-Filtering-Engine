import unicodedata
import re
from typing import Dict, Optional


HOMOGLYPH_MAP: Dict[str, str] = {
    "\u0430": "a", "\u03b1": "a", "\uff41": "a", "\u1d43": "a",
    "\u0251": "a", "\u0101": "a", "\u0103": "a", "\u0105": "a",
    "\u00e0": "a", "\u00e1": "a", "\u00e2": "a", "\u00e3": "a",
    "\u0432": "b", "\u0062": "b", "\u0180": "b", "\u1d2e": "b",
    "\u0441": "c", "\u03f2": "c", "\u217d": "c", "\u00e7": "c",
    "\u010b": "c", "\u0109": "c",
    "\u0435": "e", "\u03b5": "e", "\u212f": "e", "\u1d49": "e",
    "\u00e8": "e", "\u00e9": "e", "\u00ea": "e", "\u0113": "e",
    "\u0115": "e", "\u0117": "e", "\u0119": "e", "\u011b": "e",
    "\u04bb": "h", "\u043d": "h",
    "\u0456": "i", "\u0454": "i", "\u0131": "i", "\u1d33": "i",
    "\u00ec": "i", "\u00ed": "i", "\u00ee": "i", "\u0129": "i",
    "\u012b": "i", "\u012d": "i", "\u012f": "i",
    "\u0458": "j", "\u03f3": "j",
    "\u043a": "k", "\u0138": "k", "\u1d37": "k",
    "\u006c": "l", "\u217c": "l", "\u1d38": "l",
    "\u006d": "m", "\u043c": "m", "\u217f": "m", "\u1d39": "m",
    "\u006e": "n", "\u03b7": "n", "\u1d3a": "n",
    "\u043e": "o", "\u03bf": "o", "\uff4f": "o", "\u1d3c": "o",
    "\u00f2": "o", "\u00f3": "o", "\u00f4": "o", "\u00f5": "o",
    "\u014d": "o", "\u014f": "o", "\u0151": "o",
    "\u0440": "p", "\u03c1": "p", "\u1d3d": "p",
    "\u044f": "r",
    "\u0455": "s", "\u03c2": "s", "\u0282": "s", "\u1d46": "s",
    "\u0262": "g", "\u0067": "g", "\u0067": "g",
    "\u0442": "t", "\u03c4": "t", "\u1d3f": "t",
    "\u0443": "y", "\u03c5": "y", "\u1d4c": "y",
    "\u0076": "v", "\u03bd": "v", "\u1d5b": "v",
    "\u0077": "w", "\u03c9": "w", "\u1d48": "w",
    "\u0445": "x", "\u03c7": "x", "\u2179": "x", "\u1d4d": "x",
    "\u0079": "y", "\u0443": "y", "\u0459": "y",
    "\u007a": "z", "\u03b6": "z", "\u1d22": "z",
    "\u00f1": "n",
    "\u0391": "A", "\u0410": "A", "\uff21": "A",
    "\u0392": "B", "\u0412": "B", "\uff22": "B",
    "\u03f9": "C", "\u0421": "C", "\u217d": "C", "\uff23": "C",
    "\u0394": "D",
    "\u0395": "E", "\u0415": "E", "\uff25": "E",
    "\u039b": "L", "\uff2c": "L",
    "\u039c": "M", "\u041c": "M", "\uff2d": "M",
    "\u039d": "N", "\u0418": "N", "\uff2e": "N",
    "\u039f": "O", "\u041e": "O", "\uff2f": "O",
    "\u03a1": "P", "\u0420": "P", "\uff30": "P",
    "\u03a5": "Y", "\u04ae": "Y",
    "\u03a7": "X", "\u0425": "X", "\uff38": "X",
    "0": "o", "1": "l", "3": "e", "5": "s", "7": "t",
}

NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]")


class TextNormalizer:
    def __init__(self, homoglyph_enabled: bool = True):
        self.homoglyph_enabled = homoglyph_enabled

    def normalize(self, text: str, case_sensitive: bool = False) -> str:
        result = unicodedata.normalize("NFKC", text)
        if not case_sensitive:
            result = result.lower()
        return result

    def replace_homoglyphs(self, text: str) -> str:
        if not self.homoglyph_enabled:
            return text
        result = []
        homoglyphs_found: list = []
        for ch in text:
            mapped = HOMOGLYPH_MAP.get(ch)
            if mapped is not None and mapped != ch.lower():
                result.append(mapped)
                homoglyphs_found.append((ch, mapped))
            else:
                result.append(ch)
        return "".join(result), homoglyphs_found

    def strip_non_alnum(self, text: str, separator_chars: list = None) -> str:
        if separator_chars:
            pattern = f"[^{''.join(set('a-zA-Z0-9'))}]"
            return re.sub(pattern, "", text)
        return NON_ALNUM_RE.sub("", text)

    def strip_keep_chars(self, text: str, keep_chars: set) -> str:
        return "".join(c for c in text if c.isalnum() or c in keep_chars)

    def collapse_repeated(self, text: str, threshold: int = 2) -> str:
        if threshold <= 1:
            return re.sub(r"(.)\1+", r"\1", text)
        pattern = f"(.)\\1{{{threshold},}}"
        return re.sub(pattern, r"\1" * threshold, text)

    @staticmethod
    def get_homoglyph_map() -> Dict[str, str]:
        return dict(HOMOGLYPH_MAP)
