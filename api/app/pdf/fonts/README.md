# Bundled fonts

Used by the PDF module for every piece of user-entered text on the signature
block and the certificate page, so names in Latin or Devanagari script render
as glyphs rather than boxes.

| File                              | Source                                                   | Licence  |
|-----------------------------------|----------------------------------------------------------|----------|
| `NotoSans-Regular.ttf`, `NotoSans-Bold.ttf` | https://github.com/notofonts/latin-greek-cyrillic (hinted TTF, via notofonts.github.io) | `OFL-NotoSans.txt` |
| `NotoSansDevanagari-Regular.ttf`, `NotoSansDevanagari-Bold.ttf` | https://github.com/notofonts/devanagari (hinted TTF, via notofonts.github.io) | `OFL-NotoSansDevanagari.txt` |

Both are SIL Open Font License 1.1. The files are unmodified; reportlab
subsets them into each generated PDF. Do not swap in fonts with another
licence without an issue that asks for it.
