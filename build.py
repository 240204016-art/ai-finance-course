#!/usr/bin/env python3
"""Бір шаблоннан тесттің екі нұсқасын құрастырады.

    python3 build.py

    src/page.html + questions.json
        -> index.html     толық HTML құжат (GitHub Pages үшін)
        -> artifact.html  тек бет мазмұны (Claude артефактісі үшін)

Сұрақты не жауапты өзгерту үшін questions.json файлын,
беттің көрінісі мен логикасын өзгерту үшін src/page.html файлын түзетіп,
осы скриптті қайта іске қосыңыз.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).parent
DESCRIPTION = ("Биология пәнінен ҰБТ үлгісіндегі 40 сұрақтан тұратын "
               "онлайн тест: таймер, сұрақтар картасы және толық талдау.")

HEAD = """<!doctype html>
<html lang="kk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="{description}">
<meta name="color-scheme" content="light dark">
<style>
:root{{color-scheme:light dark;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}
body{{margin:0;font:14px system-ui,-apple-system,"Segoe UI",sans-serif}}
img{{max-width:100%}}
[hidden]{{display:none!important}}
</style>
{head_block}</head>
<body>
{body_block}</body>
</html>
"""


def main() -> None:
    template = (ROOT / "src" / "page.html").read_text(encoding="utf-8")
    data = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if "</script" in blob.lower():
        raise SystemExit("questions.json ішінде </script> кездесті")
    page = template.replace("__DATA__", blob)

    # Артефакт нұсқасы: қабықсыз, платформа өзі орайды.
    (ROOT / "artifact.html").write_text(page, encoding="utf-8")

    # Дербес нұсқа: <title>, қаріп сілтемелері мен стильдер <head> ішіне шығады.
    split = page.index('<div class="wrap">')
    (ROOT / "index.html").write_text(
        HEAD.format(description=DESCRIPTION,
                    head_block=page[:split].strip() + "\n",
                    body_block=page[split:].strip() + "\n"),
        encoding="utf-8")

    total = sum(q["points"] for q in data["questions"])
    print(f"{len(data['questions'])} сұрақ, {total} балл -> index.html, artifact.html")


if __name__ == "__main__":
    main()
