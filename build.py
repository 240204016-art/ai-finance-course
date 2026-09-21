#!/usr/bin/env python3
"""Тесттердің веб-нұсқасын құрастырады.

    python3 build.py

    src/page.html + tests/*.json
        -> index.html     толық HTML құжат (GitHub Pages үшін)
        -> artifact.html  тек бет мазмұны (Claude артефактісі үшін)

Сұрақты не жауапты өзгерту үшін tests/ ішіндегі файлды,
беттің көрінісі мен логикасын өзгерту үшін src/page.html файлын түзетіп,
осы скриптті қайта іске қосыңыз.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).parent
TITLE = "Биология ҰБТ сынағы"
DESCRIPTION = ("Биология пәнінен ҰБТ үлгісіндегі бес нұсқа: таймер, "
               "сұрақтар картасы және әр сұрақтың толық талдауы.")

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


def load_tests():
    tests = []
    for path in sorted((ROOT / "tests").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for field in ("slug", "title", "questions"):
            if field not in data:
                raise SystemExit(f"{path.name}: '{field}' өрісі жоқ")
        data["total"] = sum(q["points"] for q in data["questions"])
        check(path.name, data)
        tests.append(data)
    if not tests:
        raise SystemExit("tests/ ішінде бірде-бір тест жоқ")
    return tests


def check(name, data):
    """Дереккөздегі қателерді құрастыру кезінде ұстау."""
    for q in data["questions"]:
        ids = {o["id"] for o in q["options"]}
        where = f"{name} Q{q['n']}"
        if q["type"] == "match":
            if len(q.get("items", [])) != 2:
                raise SystemExit(f"{where}: сәйкестендіруде 2 жұп болуы керек")
            for it in q["items"]:
                if it["answer"] not in ids:
                    raise SystemExit(f"{where}: '{it['text']}' жауабы нұсқалар арасында жоқ")
        elif q["type"] == "multi":
            if len(q.get("answer", [])) < 2:
                raise SystemExit(f"{where}: бірнеше жауапта кемінде 2 нұсқа болуы керек")
            for a in q["answer"]:
                if a not in ids:
                    raise SystemExit(f"{where}: {a} нұсқасы жоқ")
        else:
            if q.get("answer") not in ids:
                raise SystemExit(f"{where}: дұрыс жауап белгіленбеген")


def main() -> None:
    template = (ROOT / "src" / "page.html").read_text(encoding="utf-8")
    tests = load_tests()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config = {"submitUrl": cfg.get("submitUrl", "").strip()}
    payload = {"title": TITLE, "tests": tests, "config": config}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "</script" in blob.lower():
        raise SystemExit("деректер ішінде </script> кездесті")
    page = template.replace("__DATA__", blob)

    (ROOT / "artifact.html").write_text(page, encoding="utf-8")

    split = page.index('<div class="wrap">')
    (ROOT / "index.html").write_text(
        HEAD.format(description=DESCRIPTION,
                    head_block=page[:split].strip() + "\n",
                    body_block=page[split:].strip() + "\n"),
        encoding="utf-8")

    # ---- мұғалім дашборды ----
    dash_src = ROOT / "src" / "dashboard.html"
    if dash_src.exists():
        dash = dash_src.read_text(encoding="utf-8").replace("__DATA__", blob)
        d_split = dash.index('<div class="wrap">')
        (ROOT / "dashboard.html").write_text(
            HEAD.format(description="Оқушылардың тест нәтижелерін талдайтын мұғалім дашборды.",
                        head_block=dash[:d_split].strip() + "\n",
                        body_block=dash[d_split:].strip() + "\n"),
            encoding="utf-8")

    qn = sum(len(t["questions"]) for t in tests)
    pts = sum(t["total"] for t in tests)
    print(f"{len(tests)} тест, {qn} сұрақ, {pts} балл -> index.html, artifact.html")
    for t in tests:
        print(f"  {t['title']}: {len(t['questions'])} сұрақ, {t['total']} балл")
    print("нәтиже жинау: " + (config["submitUrl"] or "өшірулі (config.json бос)"))
    if dash_src.exists():
        print("дашборд: dashboard.html")


if __name__ == "__main__":
    main()
