"""
fix_features.py — восстановление картинок features в jk_data.json
1. Находит записи-дубли (одно имя в разных написаниях: кириллица/латиница/со слэшем)
2. Переносит features с картинками в запись, которую использует Excel
3. Показывает список ЖК, которым нужен перепарс
Запуск: python fix_features.py          — отчёт без изменений (dry run)
        python fix_features.py --apply  — применить изменения
"""
import json, re, sys, glob
import pandas as pd
from pathlib import Path

BASE = Path(__file__).parent
APPLY = "--apply" in sys.argv

# Транслитерация для матчинга имён
RU = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
      'и':'i','й':'i','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
      'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
      'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}

def norm(s):
    s = re.sub(r'[/\\\s\-_.,]', '', s).strip().lower()
    return ''.join(RU.get(c, c) for c in s)

def img_count(feats):
    return sum(1 for f in (feats or []) if isinstance(f, dict) and f.get('img'))

# Данные
d = json.load(open(BASE / 'jk_data.json', encoding='utf-8'))

# Имена ЖК из актуального Excel
xlsx = sorted(glob.glob(str(BASE / 'trendagent_*.xlsx')))[-1]
df = pd.read_excel(xlsx)
col_jk = next(c for c in df.columns if c == 'ЖК' or 'жк' in c.lower())
excel_names = set(str(v).strip() for v in df[col_jk].dropna() if str(v).strip() not in ('', 'nan'))
print(f"Excel: {Path(xlsx).name}, ЖК: {len(excel_names)}")
print(f"jk_data.json: {len(d)} записей\n")

# Группируем записи jk_data по нормализованному имени
groups = {}
for k in d:
    groups.setdefault(norm(k), []).append(k)

merged, need_parse, ok = [], [], []
for name in sorted(excel_names):
    entry = d.get(name)
    if entry is None:
        need_parse.append((name, 'нет записи в jk_data'))
        continue
    have = img_count(entry.get('features'))
    if have > 0:
        ok.append(name)
        continue
    # Ищем донора среди записей с тем же нормализованным именем
    donor = None
    for sib in groups.get(norm(name), []):
        if sib != name and img_count(d[sib].get('features')) > 0:
            donor = sib
            break
    if donor:
        merged.append((name, donor, img_count(d[donor]['features'])))
        if APPLY:
            entry['features'] = d[donor]['features']
            if not entry.get('about') and d[donor].get('about'):
                entry['about'] = d[donor]['about']
    else:
        need_parse.append((name, 'нет донора — нужен перепарс'))

print(f"✅ Уже с картинками: {len(ok)}")
print(f"\n🔁 Слияние из дублей ({len(merged)}):")
for name, donor, n in merged:
    print(f"   {name!r} ← {donor!r} ({n} img)")
print(f"\n🔧 Нужен перепарс ({len(need_parse)}):")
for name, why in need_parse:
    print(f"   {name!r} — {why}")

if APPLY and merged:
    # Бэкап перед записью
    (BASE / 'jk_data.backup.json').write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    (BASE / 'jk_data.json').write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n💾 Применено. Бэкап: jk_data.backup.json")
elif merged:
    print(f"\n(dry run — для применения: python fix_features.py --apply)")