"""Проверка словарей: одинаковые ключи и подстановки во всех трёх языках."""
import json
import re
import sys
from pathlib import Path

d = {l: json.loads((Path(__file__).parent.parent / "app/i18n" / f"{l}.json").read_text()) for l in ("ru", "en", "kk")}
bad = 0
for l in ("en", "kk"):
    diff = set(d["ru"]) ^ set(d[l])
    if diff:
        print(f"{l}: разные ключи: {sorted(diff)}"); bad = 1
    for k in set(d["ru"]) & set(d[l]):
        if set(re.findall(r"\{(\w+)\}", d["ru"][k])) != set(re.findall(r"\{(\w+)\}", d[l][k])):
            print(f"{l}: подстановки не совпадают в {k}"); bad = 1
print("словари в порядке:", len(d["ru"]), "ключей" if not bad else "")
sys.exit(bad)
