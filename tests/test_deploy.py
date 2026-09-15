"""The image has to contain everything the server imports, and nothing else.

`app/datasets.py` reaches into `tools/seal.py` to open the sealed dataset. That
one import is the entire reason `tools/` appears in the Dockerfile at all, and
it is exactly the kind of thing that gets found at 8pm on the night rather than
here.
"""
import ast
import fnmatch
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = re.compile(r"^COPY\s+(.+)$", re.M)

# Never in the image. Real message text, or the machinery that produces it.
FORBIDDEN = ("corpus.json", "candidates.json", "questions/", "datasets/real.json",
             "tools/mine.py", "tools/extract.py", "tools/curate.py", "poc/")


def dockerfile():
    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
        return f.read()


def dockerignore() -> list[tuple[str, bool]]:
    """The .dockerignore patterns, as (pattern, is_negation). Only the forms
    the file actually uses — plain paths, `*.ext` globs, `dir/`, and `!keep`."""
    out = []
    with open(os.path.join(ROOT, ".dockerignore"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            out.append((line.lstrip("!").rstrip("/"), neg))
    return out


def ignored(path: str, patterns: list[tuple[str, bool]]) -> bool:
    """Docker applies every pattern in order; the last match wins, so a later
    `!tools/seal.py` rescues a file an earlier `tools/` excluded."""
    verdict = False
    for pattern, neg in patterns:
        hit = (fnmatch.fnmatch(path, pattern)
               or fnmatch.fnmatch(os.path.basename(path), pattern)
               or path.startswith(pattern + "/"))
        if hit:
            verdict = not neg
    return verdict


def copied_paths() -> set[str]:
    """Every repo path the Dockerfile actually puts in the image — COPY minus
    what .dockerignore withholds from the build context. Both halves matter:
    `COPY datasets/` is only safe because the plaintext real dataset is
    excluded, and this is the test that notices if either side changes."""
    patterns = dockerignore()
    out: set[str] = set()
    for line in COPY.findall(dockerfile()):
        parts = line.split()
        for src in parts[:-1]:                      # last token is the dest
            full = os.path.join(ROOT, src)
            if os.path.isdir(full):
                for base, _, files in os.walk(full):
                    for f in files:
                        out.add(os.path.relpath(os.path.join(base, f), ROOT))
            elif os.path.exists(full):
                out.add(os.path.relpath(full, ROOT))
    return {p for p in out if not ignored(p, patterns)}


def first_party_imports(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return {m for m in mods if m.split(".")[0] in ("app", "tools")}


def test_everything_the_server_imports_is_in_the_image():
    shipped = copied_paths()
    missing = []
    for name in sorted(os.listdir(os.path.join(ROOT, "app"))):
        if not name.endswith(".py"):
            continue
        for mod in first_party_imports(os.path.join(ROOT, "app", name)):
            path = mod.replace(".", "/") + ".py"
            if path not in shipped:
                missing.append(f"app/{name} imports {mod} ({path} not copied)")
    assert not missing, "\n".join(missing)


def test_the_image_carries_no_real_data_and_no_authoring_tools():
    shipped = copied_paths()
    leaked = [p for p in shipped if any(p.startswith(f) for f in FORBIDDEN)]
    assert not leaked, f"these would ship: {leaked}"


def test_the_sealed_dataset_ships_but_the_plaintext_does_not():
    body = dockerfile()
    assert "COPY datasets/" in body
    with open(os.path.join(ROOT, ".dockerignore"), encoding="utf-8") as f:
        ignored = f.read()
    assert "datasets/real.json" in ignored          # the plaintext, not the .enc


@pytest.mark.parametrize("setting,value", [
    ("auto_stop_machines", False),
    ("min_machines_running", 1),
])
def test_the_machine_stays_awake_under_an_idle_lobby(setting, value):
    """A lobby is idle for as long as it takes two people to sit down. A
    machine that scales to zero underneath it takes the game with it."""
    import tomllib
    with open(os.path.join(ROOT, "fly.toml"), "rb") as f:
        cfg = tomllib.load(f)
    assert cfg["http_service"][setting] == value


def test_the_health_check_points_at_a_route_that_exists():
    import tomllib
    with open(os.path.join(ROOT, "fly.toml"), "rb") as f:
        cfg = tomllib.load(f)
    path = cfg["http_service"]["checks"][0]["path"]
    with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as f:
        assert f'@app.get("{path}")' in f.read()


def test_the_port_agrees_all_the_way_down():
    """fly.toml, the Dockerfile and the server's default have to be one number
    or the health check passes while nothing else works."""
    import tomllib
    with open(os.path.join(ROOT, "fly.toml"), "rb") as f:
        cfg = tomllib.load(f)
    port = cfg["http_service"]["internal_port"]
    assert cfg["env"]["PORT"] == str(port)
    assert f"PORT={port}" in dockerfile()
    with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as f:
        assert f'os.environ.get("PORT", {port})' in f.read()


def test_the_pages_ask_nobody_for_fonts():
    """A captive-portal wifi should not be able to render the game in Times."""
    for page in ("host.html", "player.html"):
        with open(os.path.join(ROOT, "static", page), encoding="utf-8") as f:
            body = f.read()
        assert "fonts.googleapis.com" not in body
        assert "fonts.gstatic.com" not in body
        assert "/static/fonts.css" in body


def test_every_font_the_css_asks_for_is_actually_here():
    with open(os.path.join(ROOT, "static", "fonts.css"), encoding="utf-8") as f:
        css = f.read()
    wanted = re.findall(r"url\(/static/(fonts/[^)]+)\)", css)
    assert wanted
    for rel in wanted:
        assert os.path.exists(os.path.join(ROOT, "static", rel)), rel
