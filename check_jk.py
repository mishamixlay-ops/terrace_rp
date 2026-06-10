import json, re

d = json.load(open('jk_data.json', encoding='utf-8'))

def norm(s):
    return re.sub(r'[/\\]', '', s).strip().lower()

print(f"Всего ЖК: {len(d)}\n")

groups = {}
for k in d:
    groups.setdefault(norm(k), []).append(k)
dups = {n: ks for n, ks in groups.items() if len(ks) > 1}
print(f"Дублей имён: {len(dups)}")
for n, ks in dups.items():
    for k in ks:
        f = d[k].get('features', [])
        wi = sum(1 for x in f if x.get('img'))
        print(f"  {k!r}: features={len(f)}, img={wi}")

ok, bad, nof = [], [], []
for k, v in d.items():
    f = v.get('features', [])
    if not f:
        nof.append(k)
    elif sum(1 for x in f if x.get('img')) == 0:
        bad.append(k)
    else:
        ok.append(k)

print(f"\nЖК с картинками: {len(ok)}")
print(f"ЖК с features БЕЗ картинок: {len(bad)}")
print(f"ЖК без features вообще: {len(nof)}")
print("\nБез картинок:")
for k in bad:
    print(f"  {k!r}")