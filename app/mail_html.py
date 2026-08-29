"""Sichere Darstellung des HTML-Teils einer E-Mail.

Aktive Inhalte, Formulare und externe Bilder werden entfernt. Die bereinigte
Mail wird zusätzlich in einem Browser-Sandbox-Iframe mit restriktiver CSP
angezeigt (siehe Frontend), damit fremdes Mail-HTML nicht Teil der Krautl-
Oberfläche wird.
"""
import re
from email import message_from_bytes, policy
from html import escape
from html.parser import HTMLParser


_ERLAUBTE_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "big", "blockquote",
    "br", "caption", "center", "cite", "code", "col", "colgroup",
    "dd", "del", "details", "div", "dl", "dt", "em", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i",
    "img", "ins", "kbd", "li", "main", "mark", "nav", "ol", "p", "pre",
    "q", "s", "samp", "section", "small", "span", "strike", "strong", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    "tt", "u", "ul", "var",
}
_LEERE_TAGS = {"br", "col", "hr", "img"}
_GESPERRTE_TAGS = {
    "applet", "audio", "base", "button", "canvas", "embed", "form", "head",
    "iframe", "input", "link", "math", "meta", "noscript", "object", "script",
    "select", "source", "style", "svg", "template", "textarea", "title", "video",
}
_IGNORIERTE_LEERE_TAGS = {"base", "embed", "input", "link", "meta", "source"}
_ERLAUBTE_ATTRIBUTE = {
    "abbr", "align", "alt", "axis", "bgcolor", "border", "cellpadding",
    "cellspacing", "char", "charoff", "colspan", "dir", "height", "lang",
    "rowspan", "scope", "span", "start", "style", "summary", "title", "valign",
    "value", "width",
}
_GEFAEHRLICHE_CSS = re.compile(
    r"(?:url\s*\(|expression\s*\(|@import|javascript\s*:|behavior\s*:|-moz-binding\s*:)",
    re.IGNORECASE,
)
_ERLAUBTES_DATENBILD = re.compile(
    r"^data:image/(?:gif|jpe?g|png|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)


def _sicherer_stil(wert: str) -> str:
    deklarationen = []
    for deklaration in wert.split(";"):
        deklaration = deklaration.strip()
        if not deklaration or ":" not in deklaration:
            continue
        eigenschaft, inhalt = deklaration.split(":", 1)
        eigenschaft = eigenschaft.strip()
        inhalt = inhalt.strip()
        if (
            not re.fullmatch(r"[-a-zA-Z]+", eigenschaft)
            or _GEFAEHRLICHE_CSS.search(inhalt)
        ):
            continue
        deklarationen.append(f"{eigenschaft}: {inhalt}")
    return "; ".join(deklarationen)


class _SicheresMailHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self.gesperrt_tiefe = 0

    def _start(self, tag: str, attrs, selbstschliessend: bool = False):
        tag = tag.lower()
        if tag in _GESPERRTE_TAGS:
            if tag not in _IGNORIERTE_LEERE_TAGS and not selbstschliessend:
                self.gesperrt_tiefe += 1
            return
        if self.gesperrt_tiefe or tag not in _ERLAUBTE_TAGS:
            return

        sichere_attribute = []
        for name, wert in attrs:
            name = name.lower()
            if wert is None or name.startswith("on"):
                continue
            if name == "src" and tag == "img":
                if _ERLAUBTES_DATENBILD.fullmatch(wert.strip()):
                    sichere_attribute.append((name, wert.strip()))
                continue
            if name not in _ERLAUBTE_ATTRIBUTE:
                continue
            if name == "style":
                wert = _sicherer_stil(wert)
                if not wert:
                    continue
            sichere_attribute.append((name, wert))

        attribute = "".join(
            f' {name}="{escape(wert, quote=True)}"'
            for name, wert in sichere_attribute
        )
        self.teile.append(f"<{tag}{attribute}>")
        if selbstschliessend and tag not in _LEERE_TAGS:
            self.teile.append(f"</{tag}>")

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, selbstschliessend=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.gesperrt_tiefe:
            if tag in _GESPERRTE_TAGS:
                self.gesperrt_tiefe = max(0, self.gesperrt_tiefe - 1)
            return
        if tag in _ERLAUBTE_TAGS and tag not in _LEERE_TAGS:
            self.teile.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.gesperrt_tiefe:
            self.teile.append(escape(data))


def html_teil_aus_mail(raw: bytes) -> str | None:
    """Liefert den bereinigten HTML-Teil oder None bei reinen Textmails."""
    nachricht = message_from_bytes(raw, policy=policy.default)
    teil = nachricht.get_body(preferencelist=("html",))
    if teil is None or teil.get_content_type() != "text/html":
        return None

    parser = _SicheresMailHTML()
    parser.feed(teil.get_content())
    parser.close()
    inhalt = "".join(parser.teile).strip()
    if not inhalt:
        return None

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html {{ color-scheme: light; background: #FDFCEE; }}
  body {{ margin: 0; padding: 18px; color: #242A1F; background: #FDFCEE; font-family: Arial, sans-serif; line-height: 1.5; overflow-wrap: anywhere; }}
  table {{ max-width: 100%; border-collapse: collapse; }}
  img {{ max-width: 100%; height: auto; }}
  pre {{ white-space: pre-wrap; }}
</style>
</head>
<body>{inhalt}</body>
</html>"""
