"""Validate Animan UML references and render the offline architecture dossier.

Requires a local PlantUML JAR, Java and Graphviz for rendering. Does not import
the application or contact an external diagram service.
"""
import argparse
import ast
from collections import Counter
from datetime import date
from html import escape
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/architecture"
CATEGORIES = {
    "classes": "Classes", "cas": "Cas d’utilisation", "sequence": "Séquences",
    "deploiement": "Déploiement", "cible": "Proposition",
}


def check_reference(reference):
    path, symbol = reference.split(":", 1)
    source = ROOT / path
    contents = source.read_text()
    if source.suffix == ".py":
        scope = ast.parse(contents).body
        node = None
        for part in symbol.split("."):
            node = next((n for n in scope if isinstance(n, (ast.ClassDef, ast.FunctionDef,
                         ast.AsyncFunctionDef)) and n.name == part), None)
            if node is None:
                raise ValueError(f"Missing Python symbol: {reference}")
            scope = node.body
        line = node.lineno
    elif source.suffix == ".kt":
        match = re.search(r"\b(?:class|object|interface)\s+" + re.escape(symbol) + r"\b", contents)
        if not match:
            raise ValueError(f"Missing Kotlin declaration: {reference}")
        line = contents[:match.start()].count("\n") + 1
    else:
        raise ValueError(f"Unsupported reference: {reference}")
    return {"path": path, "symbol": symbol, "line": line}


def inventory():
    diagrams = []
    for source in sorted((DOCS / "plantuml").glob("*.puml")):
        text = source.read_text()
        if text.count("@startuml") != 1 or text.count("@enduml") != 1:
            raise ValueError(f"Expected exactly one diagram: {source}")
        title = re.search(r"^title (.+)$", text, re.M).group(1)
        category = source.stem.split("-")[1]
        references = [check_reference(r) for r in re.findall(r"^' @source (\S+)$", text, re.M)]
        if not references and category != "cible":
            raise ValueError(f"Missing code references: {source}")
        diagrams.append({"id": source.stem, "title": title, "category": category,
                         "proposed": category == "cible", "references": references,
                         "source": "plantuml/" + source.name, "svg": "svg/" + source.stem + ".svg"})
    if len(diagrams) != 17:
        raise ValueError(f"Expected the 17 documented diagrams, found {len(diagrams)}")
    return diagrams


def gallery(diagrams, commit):
    buttons = '<button type="button" data-category="all" aria-pressed="true">Tout</button>'
    buttons += "".join(f'<button type="button" data-category="{key}" aria-pressed="false">{label}</button>'
                       for key, label in CATEGORIES.items())
    figures = []
    for item in diagrams:
        title = escape(item["title"])
        refs = "".join(f'<li><a href="../../{ref["path"]}#L{ref["line"]}">'
                       f'{escape(ref["symbol"])}</a> — <code>{escape(ref["path"])}</code></li>'
                       for ref in item["references"])
        figures.append(f'''<article data-category="{item['category']}" id="{item['id']}">
<h2>{title}</h2><p class="kind">{CATEGORIES[item['category']]}
{' · Architecture proposée, non implémentée' if item['proposed'] else ' · Architecture observée'}</p>
<div class="actions"><button type="button" class="zoom" data-svg="{item['svg']}"
data-title="{title}" data-width="{item['width']}">Agrandir</button>
<a href="{item['svg']}" target="_blank" rel="noopener">SVG original</a>
<a href="{item['source']}">Source PlantUML</a><a href="#{item['id']}">Lien direct</a></div>
<figure><img src="{item['svg']}" width="{item['width']}" height="{item['height']}"
loading="lazy" alt="{title}"><figcaption>{title}</figcaption></figure>
{'<details><summary>Références vérifiées dans le code</summary><ul>'+refs+'</ul></details>' if refs else ''}
</article>''')
    counts = Counter(d["category"] for d in diagrams)
    summary_labels = {**CATEGORIES, "deploiement": "déploiements"}
    summary = " · ".join(f"{counts[k]} {v.lower()}" for k, v in summary_labels.items())
    return '''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Animan — dossier UML et architecture</title>
<style>
:root{color-scheme:light dark;--bg:#f5f6fb;--fg:#172033;--surface:#fff;--muted:#536174;--line:#d5d9e4;--accent:#6d28d9}
@media(prefers-color-scheme:dark){:root{--bg:#101422;--fg:#edf0f6;--surface:#191f31;--muted:#bac3d6;--line:#3b455c;--accent:#c4a7ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
header,main,footer{max-width:1440px;margin:auto;padding:24px}h1{font-size:clamp(24px,4vw,38px);line-height:1.2}
h2{font-size:21px;line-height:1.35;margin:0 0 8px}p{max-width:90ch}a{color:var(--accent);overflow-wrap:anywhere}
button,input{font:inherit;color:inherit;background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:9px 13px}
button{cursor:pointer}button:hover,button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
nav,.actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap}nav{margin:20px 0}input{max-width:100%;width:420px}
.kind,footer{color:var(--muted)}article{background:var(--surface);padding:24px;margin-bottom:30px;border-radius:10px;scroll-margin-top:18px}
article[hidden]{display:none}.actions{margin:14px 0 18px}.actions a{font-size:14px}
figure{margin:0;background:#fff;overflow:auto}figure img{display:block;width:100%;height:auto;max-height:78vh;object-fit:contain}
figcaption{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
details{margin-top:16px}details ul{padding-left:22px;font-size:14px}code{overflow-wrap:anywhere}
dialog{width:96vw;max-width:96vw;height:94vh;max-height:94vh;padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--fg)}
dialog::backdrop{background:#000b}.dialog-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.dialog-bar strong{flex:1;min-width:200px}.viewport{height:calc(100% - 88px);overflow:auto;background:#fff}
.viewport img{display:block;max-width:none;height:auto}.empty{padding:20px}footer{font-size:14px}
@media(max-width:600px){header,main,footer{padding:16px}article{padding:14px}.dialog-bar strong{flex-basis:100%}.viewport{height:calc(100% - 150px)}}
@media print{@page{size:A3 landscape;margin:12mm}body{background:#fff;color:#111}header{padding:0}nav,.actions,.search,details,dialog,footer{display:none!important}
main{max-width:none;padding:0}article{break-before:page;break-inside:avoid;background:#fff;padding:0;border-radius:0;margin:0}
figure img{max-height:220mm;width:100%;height:220mm;object-fit:contain}a{color:#111}.kind{color:#333}}
</style></head><body><header>
<h1>Animan — dossier UML</h1>
<p>@@SUMMARY@@. Les vues de l’existant sont issues du code ; la vue verte décrit une évolution proposée.</p>
<p><a href="README.md">Cas d’utilisation détaillés et axes d’amélioration</a> · Révision analysée : <code>@@COMMIT@@</code>.</p>
<nav aria-label="Familles de diagrammes">@@BUTTONS@@<button type="button" id="print">Imprimer la sélection</button></nav>
<div class="search"><label for="filter">Filtrer les titres</label> <input id="filter" type="search" placeholder="Ex. : Android, reprise, classes…"></div>
<p id="count" role="status" aria-live="polite">17 diagrammes affichés</p></header>
<main>@@FIGURES@@<p class="empty" id="empty" hidden>Aucun diagramme ne correspond à ce filtre.</p></main>
<dialog id="viewer" aria-labelledby="viewer-title"><div class="dialog-bar"><strong id="viewer-title"></strong>
<button type="button" id="minus" aria-label="Réduire le diagramme">−</button><span id="scale"></span>
<button type="button" id="plus" aria-label="Agrandir le diagramme">+</button><button type="button" id="fit">Ajuster</button>
<button type="button" id="close">Fermer</button></div><div class="viewport" tabindex="0" aria-label="Diagramme agrandi, défilement disponible"><img id="large" alt=""></div></dialog>
<footer>Consultation hors ligne. Les liens de code nécessitent le dépôt complet. Les diagrammes décrivent le code ; ils ne remplacent pas les tests de fonctionnement.</footer>
<script>
const articles=[...document.querySelectorAll('article')], input=document.getElementById('filter');let category='all';
const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
function filter(){let count=0;for(const item of articles){item.hidden=!(category==='all'||item.dataset.category===category)||!norm(item.querySelector('h2').textContent).includes(norm(input.value));if(!item.hidden)count++}
document.getElementById('count').textContent=count+' diagramme'+(count===1?'':'s')+' affiché'+(count===1?'':'s');document.getElementById('empty').hidden=count>0}
document.querySelectorAll('nav [data-category]').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.category;document.querySelectorAll('nav [data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));filter()}));input.addEventListener('input',filter);
document.getElementById('print').addEventListener('click',()=>window.print());
const viewer=document.getElementById('viewer'),large=document.getElementById('large'),viewport=document.querySelector('.viewport');let width=1000,factor=1;
function scale(){large.style.width=Math.round(width*factor)+'px';document.getElementById('scale').textContent=Math.round(factor*100)+' %'}
function fit(){factor=Math.min(1,Math.max(.1,(viewport.clientWidth-20)/width));scale()}
document.querySelectorAll('.zoom').forEach(button=>button.addEventListener('click',()=>{if(!viewer.showModal){window.open(button.dataset.svg,'_blank','noopener');return}width=Number(button.dataset.width);large.src=button.dataset.svg;large.alt=button.dataset.title;document.getElementById('viewer-title').textContent=button.dataset.title;viewer.showModal();fit();viewport.scrollTop=0;viewport.scrollLeft=0}));
document.getElementById('close').addEventListener('click',()=>viewer.close());document.getElementById('plus').addEventListener('click',()=>{factor=Math.min(3,factor*1.25);scale()});document.getElementById('minus').addEventListener('click',()=>{factor=Math.max(.1,factor/1.25);scale()});document.getElementById('fit').addEventListener('click',fit);
if(location.hash){const target=document.getElementById(location.hash.slice(1));if(target)target.scrollIntoView()}
</script></body></html>
'''.replace("@@SUMMARY@@", escape(summary)).replace("@@COMMIT@@", escape(commit)).replace(
        "@@BUTTONS@@", buttons).replace("@@FIGURES@@", "\n".join(figures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plantuml-jar", type=Path, default=Path("/usr/share/plantuml/plantuml.jar"))
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    diagrams = inventory()
    print(f"Validated {sum(len(d['references']) for d in diagrams)} source references in {len(diagrams)} diagrams.", flush=True)
    if args.check_only:
        return
    if not args.plantuml_jar.is_file():
        raise FileNotFoundError("Pass a local PlantUML JAR using --plantuml-jar")
    subprocess.run(["java", "-Xmx512m", "-Djava.awt.headless=true", "-jar", str(args.plantuml_jar),
                    "-charset", "UTF-8", "-tsvg", "-o", "../svg",
                    str(DOCS / "plantuml/*.puml")], cwd=ROOT, check=True, timeout=240)
    for item in diagrams:
        path = DOCS / item["svg"]
        text = path.read_text()
        root = ET.fromstring(text)
        if "syntax error" in " ".join(root.itertext()).lower():
            raise ValueError(f"PlantUML error diagram: {path}")
        item["width"] = int(root.attrib["width"].removesuffix("px"))
        item["height"] = int(root.attrib["height"].removesuffix("px"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {"analysis_date": date.today().isoformat(), "analyzed_commit": commit,
                "scope": "repository source analysis; not runtime validation", "diagrams": diagrams}
    (DOCS / "diagrams.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (DOCS / "index.html").write_text(gallery(diagrams, commit[:12]))
    archive = ROOT / "build/architecture/animan-uml.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    paths = [DOCS / n for n in ("README.md", "index.html", "diagrams.json")]
    paths += sorted((DOCS / "plantuml").glob("*")) + sorted((DOCS / "svg").glob("*.svg"))
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in paths:
            output.write(path, "animan-uml/" + path.relative_to(DOCS).as_posix())
    with ZipFile(archive) as output:
        if output.testzip() is not None:
            raise ValueError("Invalid export ZIP")
    print(f"Rendered {len(diagrams)} SVGs and offline gallery. Verified archive: {archive}")


if __name__ == "__main__":
    main()
