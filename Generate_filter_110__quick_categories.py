# ACTUAL VERSION: v110 (source: Generate_filter_110__quick_categories.py)
# ACTUAL VERSION: v110 (source: Generate_filter_110__quick_categories.py)
# ACTUAL VERSION: v110 (source: Generate_filter_110__quick_categories.py)
# ACTUAL VERSION: v110 (source: Generate_filter_110__quick_categories.py)
#!/usr/bin/env python3
"""
Генератор HTML-фильтра для данных TrendAgent.
Запуск: python generate_filter.py

Нелинейный слайдер: 80% шкалы = P5–P90 (основная масса квартир),
последние 20% = P90–max (выбросы). Удобно выбирать обычные квартиры,
дорогие/большие не теряются.
"""

import os
import pandas as pd
import json
import re
import glob
import urllib.parse
import socket
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # читаем .env из папки скрипта

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

BASE_DIR    = Path(__file__).parent
OUTPUT_FILE = BASE_DIR / "index.html"

# ── Google Sheets (рассрочки и ипотека) ──────────────────────
SHEETS_KEY_FILE    = BASE_DIR / os.getenv("SHEETS_KEY_FILE", "qualified-cacao-490317-d7-2d6a6f53f82d.json")
MORTGAGE_SHEET_ID  = os.getenv("MORTGAGE_SHEET_ID", "1or19DcE4LruFcb8WpDOpRLoTyvTc3T73HYBaUcp4Z9E")
INSTALL_SHEET_ID   = os.getenv("INSTALL_SHEET_ID",  "1SdqN7pe3bggjmz6jWeezWaAJdtuKLD48loTqxYVMaN0")

# ── Яндекс Object Storage: URL папки с filter.css и filter.js ──────────────
# Установи свой URL (без слеша на конце):
# Пример: https://storage.yandexcloud.net/my-bucket
YANDEX_CLOUD_BASE_URL = "https://storage.yandexcloud.net/royaltyplace/terrace"
# Версия сборки — добавляется к filter.css/filter.js для сброса кэша браузера
import time
BUILD_VERSION = int(time.time())

# URL основного сайта (для шаринга и OG-редиректа)
MAIN_SITE_URL = "https://terrace-royaltyplace.ru"
SHARE_VERSION = 2  # Увеличивай на 1 при каждом обновлении базы чтобы сбросить кэш Telegram

# Google Apps Script для лайков
APPS_SCRIPT_LIKES_URL = "https://script.google.com/macros/s/AKfycbz8BPTiHYxzWHRxLyVT-gFMlikRpnUs5X2K6B6B1bTdikUBn0dck-3eL_qrowYQ5WTP/exec"


# ──────────────────────────────────────────────
# GOOGLE SHEETS — РАССРОЧКИ И ИПОТЕКА
# ──────────────────────────────────────────────
# ── Транслитерация рус→лат ──────────────────────────────────
_RU_TO_LAT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
    'и':'i','й':'i','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
}

def _translit(text):
    return ''.join(_RU_TO_LAT.get(ch, ch) for ch in text.lower())

def _normalize(text):
    """Нормализует строку: lower + убирает префикс ЖК."""
    t = text.strip().lower()
    for prefix in ("жк ", "жк. ", "кп ", "апарт-отель ", "объекты:\n", "объекты: \n"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    return t

def _first_word(text):
    """Первое значимое слово (длиннее 3 символов)."""
    words = re.split(r'[\s,./\\()\-]', text.lower())
    for w in words:
        if len(w) > 3:
            return w
    return text.lower()[:4] if len(text) > 3 else ""

def _jk_matches_cell(jk_name, cell_text, developer=""):
    """
    Проверяет совпадение ЖК с ячейкой таблицы.
    Ищет по каждой строке ячейки отдельно.
    Учитывает транслитерацию (Альпен ↔ Alpen).
    Матчинг по первому слову ЖК (Любоград в Стрельне ↔ Любоград 5 оч.)
    """
    jk_norm  = _normalize(jk_name)
    jk_tr    = _translit(jk_norm)
    jk_first = _first_word(jk_norm)
    jk_first_tr = _translit(jk_first)
    dev_norm = developer.lower().strip() if developer else ""

    for line in cell_text.split('\n'):
        line_norm = _normalize(line)
        line_tr   = _translit(line_norm)
        line_raw  = line.strip().lower()

        if not line_norm or len(line_norm) < 2:
            continue

        # 1. Прямое вхождение полного названия
        if jk_norm and (jk_norm in line_norm or jk_norm in line_raw):
            return True
        # 2. Транслит полного названия
        if jk_tr and len(jk_tr) > 3 and jk_tr in line_tr:
            return True
        # 3. Строка содержится в названии ЖК
        if len(line_norm) > 3 and jk_norm and line_norm in jk_norm:
            return True
        # 4. Транслит строки в названии
        if len(line_tr) > 3 and jk_tr and line_tr in jk_tr:
            return True
        # 5. Совпадение по первому слову (Любоград ↔ Любоград 5 оч.)
        line_first = _first_word(line_norm)
        line_first_tr = _translit(line_first)
        if jk_first and len(jk_first) > 3:
            if jk_first == line_first:
                return True
            if jk_first_tr and jk_first_tr == line_first_tr:
                return True

    # 6. Поиск по застройщику
    if dev_norm and len(dev_norm) > 3:
        for line in cell_text.split('\n'):
            line_norm = _normalize(line)
            if dev_norm in line_norm or _translit(dev_norm) in _translit(line_norm):
                return True

    return False


def load_sheets_data():
    """Загружает рассрочки и ипотеку из Google Sheets. Возвращает (inst_data, mort_data)."""
    if not GSPREAD_AVAILABLE:
        print("⚠️  gspread не установлен — рассрочки/ипотека недоступны")
        return {}, {}
    if not SHEETS_KEY_FILE.exists():
        print(f"⚠️  JSON ключ не найден: {SHEETS_KEY_FILE.name}")
        return {}, {}
    try:
        print("📡 Подключаюсь к Google Sheets...")
        _old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(15)
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds  = Credentials.from_service_account_file(str(SHEETS_KEY_FILE), scopes=scopes)
        gc     = gspread.authorize(creds)

        # ── Рассрочки ────────────────────────────────────────
        print("   → Загружаю рассрочки...")
        sh_inst   = gc.open_by_key(INSTALL_SHEET_ID)
        ws_inst   = sh_inst.worksheet("Рассрочки. Санкт-Петербург")
        inst_rows = ws_inst.get_all_values()
        hr_inst   = None
        for i, row in enumerate(inst_rows):
            if "Застройщик" in [h.strip() for h in row] and "ЖК" in [h.strip() for h in row]:
                hr_inst = i; break
        inst_headers = [h.strip() for h in inst_rows[hr_inst]]

        def find_header(headers, *variants):
            for i, h in enumerate(headers):
                for v in variants:
                    if v.lower() in h.lower():
                        return i
            return None

        jk_c   = find_header(inst_headers, "жк")
        name_c = find_header(inst_headers, "маркетинговое название")
        pv_c   = find_header(inst_headers, "пв", "первоначальный")
        srok_c = find_header(inst_headers, "срок рассрочки")
        est_c  = find_header(inst_headers, "есть рассрочка")
        dev_c  = find_header(inst_headers, "застройщик")

        if None in (jk_c, name_c, pv_c, srok_c, est_c):
            print(f"⚠️  Не найдены колонки рассрочек: jk={jk_c} name={name_c} pv={pv_c} srok={srok_c} est={est_c}")
            return {}, {}

        # Группируем рассрочки по jk_key
        inst_by_jk = {}  # jk_name -> list of {name, pv, srok}
        for row in inst_rows[hr_inst+1:]:
            if len(row) <= jk_c: continue
            est = row[est_c].strip() if len(row) > est_c else ""
            if est in ("Нет", "Нет Рассрочки", ""): continue
            cell_jk  = row[jk_c]
            cell_dev = row[dev_c].strip() if dev_c and len(row) > dev_c else ""
            name = row[name_c].strip() if len(row) > name_c else ""
            pv   = row[pv_c].strip()   if len(row) > pv_c   else ""
            srok = row[srok_c].strip() if len(row) > srok_c else ""
            if not name or name.lower() == "нет рассрочки": continue
            key = cell_jk.strip()
            if key not in inst_by_jk:
                inst_by_jk[key] = []
            entry = {"name": name, "pv": pv, "srok": srok, "dev": cell_dev}
            if entry not in inst_by_jk[key]:
                inst_by_jk[key].append(entry)

        # ── Ипотека (Субсидирование СПб) ─────────────────────
        print("   → Загружаю ипотеку...")
        sh_mort  = gc.open_by_key(MORTGAGE_SHEET_ID)
        ws_sub   = sh_mort.worksheet("Субсидирование СПб")
        sub_rows = ws_sub.get_all_values()
        hr_sub   = None
        for i, row in enumerate(sub_rows):
            if "Объект" in row and "Банк" in row:
                hr_sub = i; break

        ws_nopv   = sh_mort.worksheet("Ипотека без ПВ от Застройщика")
        nopv_rows = ws_nopv.get_all_values()
        hr_nopv   = None
        for i, row in enumerate(nopv_rows):
            if "Объект" in row and len([x for x in row if x.strip()]) > 2:
                hr_nopv = i; break

        mort_data = {
            "sub_rows": sub_rows, "hr_sub": hr_sub,
            "nopv_rows": nopv_rows, "hr_nopv": hr_nopv,
        }

        print(f"✅ Google Sheets загружены: {sum(len(v) for v in inst_by_jk.values())} рассрочек")
        socket.setdefaulttimeout(_old_timeout)
        return inst_by_jk, mort_data

    except Exception as e:
        socket.setdefaulttimeout(_old_timeout)
        print(f"⚠️  Ошибка загрузки Google Sheets: {e}")
        return {}, {}




def _extract_min_rate_vsrok(text):
    """Ищет минимальную ставку с пометкой 'на весь срок' в тексте."""
    if not text or text == "-":
        return None
    matches = re.findall(r'([\d]+[.,][\d]+)%\s+на\s+весь\s+срок', text, re.IGNORECASE)
    if not matches:
        return None
    rates = []
    for m in matches:
        try:
            rates.append(float(m.replace(',', '.')))
        except:
            pass
    return min(rates) if rates else None


def _extract_min_rate_any(text):
    """
    Ищет минимальную ставку в тексте.
    Возвращает (rate_float, period_str) где period_str например "на весь срок" или "на 1 год".
    """
    if not text or text == "-":
        return None, None

    candidates = []

    # Паттерн: "Ставка X% на Y срок/лет/год"
    for m in re.finditer(r'[Сс]тавка\s+([\d]+[.,]?[\d]*)%\s+на\s+([\w\s]+?)(?:\n|$|,)', text):
        try:
            rate = float(m.group(1).replace(',', '.'))
            period = m.group(2).strip().rstrip('.')
            if 0.01 <= rate <= 30:
                candidates.append((rate, "на " + period))
        except:
            pass

    # Паттерн: "X% на весь срок" без слова Ставка
    for m in re.finditer(r'([\d]+[.,][\d]+)%\s+на\s+весь\s+срок', text, re.IGNORECASE):
        try:
            rate = float(m.group(1).replace(',', '.'))
            candidates.append((rate, "на весь срок"))
        except:
            pass

    if not candidates:
        # Fallback — любое X.X% в тексте
        for m in re.finditer(r'([\d]+[.,][\d]+)%', text):
            try:
                rate = float(m.group(1).replace(',', '.'))
                if 0.01 <= rate <= 30:
                    candidates.append((rate, ""))
            except:
                pass

    if not candidates:
        return None, None

    best = min(candidates, key=lambda x: x[0])
    return best


def _apt_type_allowed(jk_cell_text, apt_type_raw, known_jk_names=None):
    """
    Проверяет подходит ли квартира по типу для данной рассрочки.
    Убирает названия ЖК из текста — остаётся только условие.
    """
    # Убираем известные названия ЖК — остаётся только условие
    cleaned = jk_cell_text
    if known_jk_names:
        for jk in known_jk_names:
            for variant in [jk, _translit(jk.lower())]:
                try:
                    cleaned = re.sub(re.escape(variant), '', cleaned, flags=re.IGNORECASE)
                except:
                    pass
    text = cleaned.lower()

    # Нормализуем тип квартиры
    apt = str(apt_type_raw).strip().lower()
    is_studio = "студ" in apt
    num_match = re.search(r'(\d+)', apt)
    apt_num = int(num_match.group(1)) if num_match else 0
    is_euro = "е" in apt and apt_num > 0

    # После вырезания ЖК ищем ограничения:
    # 1. Скобочный текст: "(только X)", "(кроме X)"
    bracket_hints   = re.findall(r'\(([^)]+)\)', text)
    # 2. Явные "только X" / "кроме X"
    explicit_only   = re.findall(r'только\s+([^\n,\(]+)', text)
    explicit_except = re.findall(r'кроме\s+([^\n,\(]+)', text)
    # 3. "на X-к.кв" / "на студии" — остаток после вырезания ЖК
    residual_on     = re.findall(r'на\s+([^\n,\(]+(?:-к\.кв|студи|комн)[^\n,\(]*)', text)

    all_only   = " ".join(bracket_hints + explicit_only + residual_on).lower()
    all_except = " ".join(explicit_except).lower()

    has_only   = bool(all_only.strip()) and any(k in all_only for k in
                     ["студи", "1-к", "2-к", "3-к", "4-к", "1кк", "2кк", "3кк", "студ"])
    has_except = bool(all_except.strip()) and any(k in all_except for k in
                     ["студи", "1-к", "2-к", "3-к", "4-к", "студ"])

    if not has_only and not has_except:
        return True  # нет ограничений — подходит всем

    def type_in_text(hint_text):
        if is_studio and ("студи" in hint_text or "студ" in hint_text):
            return True
        for n in range(1, 6):
            if f"{n}-к" in hint_text or f"{n}кк" in hint_text:
                if apt_num == n:
                    return True
        return False

    if has_except:
        if type_in_text(all_except):
            return False
        return True

    if has_only:
        return type_in_text(all_only)

    return True


def _parse_pv(pv_str):
    """Извлекает числовое значение ПВ из строки типа '30%' или '30'."""
    m = re.search(r'(\d+)', str(pv_str))
    return int(m.group(1)) if m else 999


def get_installments_for_jk(jk_name, inst_by_jk, developer="", apt_type_raw="", known_jk_names=None):
    """Возвращает до 4 самых выгодных рассрочек для данного ЖК."""
    results = []
    seen = set()
    for cell_jk, entries in inst_by_jk.items():
        jk_match  = _jk_matches_cell(jk_name, cell_jk, developer)
        dev_match = False
        if developer and entries:
            cell_dev = entries[0].get("dev", "")
            if cell_dev and developer.lower() in cell_dev.lower():
                dev_match = True
        if not jk_match and not dev_match:
            continue
        for e in entries:
            key = (e["name"], e["pv"], e["srok"])
            if key not in seen:
                # Проверяем тип квартиры если задан
                if apt_type_raw and not _apt_type_allowed(cell_jk, apt_type_raw, known_jk_names):
                    continue
                seen.add(key)
                results.append(e)

    if not results:
        return []

    # Сортируем по ПВ (меньше = выгоднее)
    results_sorted = sorted(results, key=lambda r: _parse_pv(r["pv"]))

    # Берём уникальные по названию — не дублируем одно и то же
    seen_names = set()
    unique = []
    for r in results_sorted:
        name_key = r["name"].lower().strip()
        if name_key not in seen_names:
            seen_names.add(name_key)
            unique.append(r)

    return unique[:4]


def get_mortgage_for_jk(jk_name, mort_data, developer=""):
    """Возвращает мин. ставки Семейной и Стандартной ипотеки из Субсидирование СПб."""
    # ПИК считает индивидуально — не ищем по ЖК
    is_pik = "пик" in developer.lower()

    MARKET_STD_RATE = 19.0  # текущая рыночная ставка март 2026

    if not mort_data:
        results = []
        results.append({"prog": "Семейная", "rate": "6%", "term": "на весь срок", "default": True})
        results.append({"prog": "Стандартная", "rate": f"{MARKET_STD_RATE}%", "term": "", "default": True, "market": True})
        return results

    sub_rows = mort_data.get("sub_rows", [])
    hr_sub   = mort_data.get("hr_sub")
    if hr_sub is None:
        return []

    # Определяем колонки по заголовкам
    header_row = sub_rows[hr_sub] if hr_sub < len(sub_rows) else []
    col_std, col_fam = 5, 6
    for i, h in enumerate(header_row):
        h_low = h.lower()
        if "семейн" in h_low: col_fam = i
        elif "стандарт" in h_low: col_std = i

    all_fam_rates   = []
    all_std_rates   = []

    for row in sub_rows[hr_sub+1:]:
        obj = row[2].strip() if len(row) > 2 else ""
        if is_pik:
            if "пик" not in obj.lower(): continue
        else:
            if not _jk_matches_cell(jk_name, obj, developer): continue

        fam_text = row[col_fam].strip() if len(row) > col_fam else ""
        std_text = row[col_std].strip() if len(row) > col_std else ""

        rate_fam, term_fam = _extract_min_rate_any(fam_text)
        rate_std, term_std = _extract_min_rate_any(std_text)

        if rate_fam is not None:
            all_fam_rates.append((rate_fam, term_fam or "на весь срок"))
        if rate_std is not None:
            all_std_rates.append((rate_std, term_std or "на весь срок"))

    results = []

    # Семейная
    if all_fam_rates:
        best = min(all_fam_rates, key=lambda x: x[0])
        rate_val, term = best
        rate_str = (str(int(rate_val)) if rate_val == int(rate_val)
                    else f"{rate_val:.2f}".rstrip('0').rstrip('.'))
        results.append({"prog": "Семейная", "rate": rate_str + "%",
                        "term": term, "default": False})
    else:
        results.append({"prog": "Семейная", "rate": "6%",
                        "term": "на весь срок", "default": True})

    # Стандартная
    if all_std_rates:
        best = min(all_std_rates, key=lambda x: x[0])
        rate_val, term = best
        rate_str = (str(int(rate_val)) if rate_val == int(rate_val)
                    else f"{rate_val:.2f}".rstrip('0').rstrip('.'))
        results.append({"prog": "Стандартная", "rate": rate_str + "%",
                        "term": term, "default": False})
    else:
        rate_str = str(int(MARKET_STD_RATE)) if MARKET_STD_RATE == int(MARKET_STD_RATE) else str(MARKET_STD_RATE)
        results.append({"prog": "Стандартная", "rate": rate_str + "%",
                        "term": "", "default": True, "market": True})

    return results


# ──────────────────────────────────────────────
# ПОИСК ФАЙЛОВ
# ──────────────────────────────────────────────
def find_latest_excel():
    files = sorted(glob.glob(str(BASE_DIR / "trendagent_*.xlsx")))
    if not files:
        raise FileNotFoundError("❌ Файл trendagent_*.xlsx не найден рядом со скриптом")
    print(f"📂 Excel: {Path(files[-1]).name}")
    return files[-1]

def find_latest_layouts():
    # Сначала проверяем папку layouts/ (новая структура)
    plain = BASE_DIR / "layouts"
    if plain.exists():
        print(f"📂 Планировки: layouts/")
        return plain
    # Fallback: layouts_* (старая структура)
    dirs = sorted(glob.glob(str(BASE_DIR / "layouts_*")))
    if dirs:
        print(f"📂 Планировки: {Path(dirs[-1]).name}/")
        return Path(dirs[-1])
    print("⚠️  Папка layouts не найдена")
    return None

# ──────────────────────────────────────────────
# УТИЛИТЫ
# ──────────────────────────────────────────────
def find_col(df, *variants):
    for col in df.columns:
        for v in variants:
            if v.lower() in col.lower():
                return col
    return None

def parse_price(val):
    if pd.isna(val): return 0.0
    s = re.sub(r'[^\d]', '', str(val))
    try: return float(s)
    except: return 0.0

def fmt_price(p):
    if p <= 0: return 'По запросу'
    return f"{int(p):,}".replace(',', ' ') + ' ₽'

def parse_float(val):
    if pd.isna(val): return 0.0
    s = re.sub(r'[^\d.,]', '', str(val)).replace(',', '.')
    try: return float(s)
    except: return 0.0

def parse_floor(val):
    if pd.isna(val): return 0
    s = str(val).split('/')[0].strip()
    try: return int(float(re.sub(r'[^\d.]', '', s)))
    except: return 0

def normalize_type(val):
    # Маппинг: Студия->0, 1к/2Е->1, 2к/3Е->2, 3к/4Е->3, 4к+->4plus, Своб.план->free
    if pd.isna(val): return '1', '1 комната'
    s = str(val).strip()
    sl = s.lower()
    if 'своб' in sl or 'free' in sl: return 'free', 'Своб. план'
    if 'студ' in sl: return '0', 'Студия'
    m = re.search(r'(\d+)', s)
    if m:
        n = int(m.group(1))
        is_euro = bool(re.search(r'е', sl))  # 2Е, 3Е, 4Е
        if n == 1:           return '1', '1 комната'   # 1к
        elif n == 2:
            if is_euro:      return '1', '1 комната'   # 2Е -> 1 комната
            else:            return '2', '2 комнаты'   # 2к -> 2 комнаты
        elif n == 3:
            if is_euro:      return '2', '2 комнаты'   # 3Е -> 2 комнаты
            else:            return '3', '3 комнаты'   # 3к -> 3 комнаты
        elif n == 4:
            if is_euro:      return '3', '3 комнаты'   # 4Е -> 3 комнаты
            else:            return '4plus', '4+ комнат' # 4к -> 4+
        else:                return '4plus', '4+ комнат' # 5к и выше -> 4+
    return '1', s

def find_layout_image(layouts_dir, row_num):
    if not layouts_dir: return ''
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        f = layouts_dir / f"apt_{row_num:04d}.{ext}"
        if f.exists(): return f.name
    return ''

def percentile(vals_sorted, pct):
    if not vals_sorted: return 0
    n = len(vals_sorted)
    return vals_sorted[min(n - 1, max(0, int(n * pct / 100)))]

# ──────────────────────────────────────────────
# НЕЛИНЕЙНЫЙ ДИАПАЗОН ДЛЯ СЛАЙДЕРА
# Возвращает dict с полями:
#   min       — абсолютный минимум
#   break80   — значение на отметке 80% шкалы (P90 данных)
#   max       — абсолютный максимум
#   nonlinear — True если выброс значительный (макс > 1.5 * P90)
# ──────────────────────────────────────────────
def slider_range(apartments, key):
    vals = sorted(a[key] for a in apartments if a[key] > 0)
    if not vals:
        return {"min": 0, "break80": 100, "max": 100, "nonlinear": False}
    v_min   = vals[0]
    v_p90   = percentile(vals, 90)
    v_max   = vals[-1]
    nonlin  = v_max > v_p90 * 1.5   # выброс значительный?
    return {
        "min":      v_min,
        "break80":  v_p90,
        "max":      v_max,
        "nonlinear": nonlin,
    }

# ──────────────────────────────────────────────
# ЗАГРУЗКА ДАННЫХ
# ──────────────────────────────────────────────
def load_data(excel_path, layouts_dir):
    df = pd.read_excel(excel_path)
    print(f"\n⚙️  Колонки: {list(df.columns)}")
    print(f"⚙️  Строк:   {len(df)}")

    # Загружаем данные из Google Sheets
    inst_by_jk, mort_data = load_sheets_data()

    # Загружаем данные ЖК (текст, карточки, акции)
    jk_data_file = BASE_DIR / "jk_data.json"
    jk_data_all = {}
    if jk_data_file.exists():
        try:
            import json as _json
            jk_data_all = _json.loads(jk_data_file.read_text(encoding="utf-8"))
            print(f"✅ jk_data.json загружен: {len(jk_data_all)} ЖК")
        except Exception as e:
            print(f"⚠️  Ошибка загрузки jk_data.json: {e}")
    print(f"[DEBUG] inst_by_jk keys: {list(inst_by_jk.keys())[:5]}")
    print(f"[DEBUG] mort_data keys: {list(mort_data.keys()) if mort_data else 'EMPTY'}")

    col_type     = find_col(df, 'тип', 'type', 'комн')
    col_area     = find_col(df, 's пр', 'пл.общ', 'площ', 's общ', 'area')
    col_kitchen  = find_col(df, 's кух', 'кухн', 'kitchen')
    col_floor    = find_col(df, 'эт', 'floor', 'этаж')
    col_price      = find_col(df, '100%', 'цена', 'price', 'стоим')
    col_base_price = find_col(df, 'базов', 'Базовая')
    col_finish   = find_col(df, 'отд', 'finish', 'отдел')
    col_district = find_col(df, 'район', 'district')
    col_layout   = find_col(df, 'планировк', 'layout')
    col_num      = find_col(df, '№', 'num', 'номер')
    col_jk       = find_col(df, 'жк', 'ЖК', 'комплекс', 'объект')
    col_deadline = find_col(df, 'сдач', 'сдача', 'срок', 'квартал', 'deadline')
    col_reward    = find_col(df, 'вознагр', 'reward', 'комисс')
    col_developer = find_col(df, 'застр', 'developer', 'застройщ')
    col_status   = find_col(df, 'статус', 'status')
    col_view     = find_col(df, 'видовая квартира', 'видовая_квартира')

    CLOUD_BASE = 'https://storage.yandexcloud.net/royaltyplace/terrace'

    print(f"\n📌 Маппинг колонок:")
    for name, col in [('Тип', col_type), ('Площадь', col_area), ('Кухня', col_kitchen),
                      ('Этаж', col_floor), ('Цена', col_price), ('Отделка', col_finish),
                      ('Район', col_district), ('Планировка', col_layout),
                      ('ЖК', col_jk), ('Сдача', col_deadline), ('Видовая', col_view)]:
        print(f"   {name:<12}: {('✅ \"' + col + '\"') if col else '❌ не найдена'}")

    apartments = []
    all_jk_names = [str(v).strip() for v in df[col_jk].dropna().unique() if str(v).strip()] if col_jk else []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        try:
            r_raw, r_display = normalize_type(row.get(col_type) if col_type else None)
            area    = parse_float(row.get(col_area)    if col_area    else 0)
            kitchen = parse_float(row.get(col_kitchen) if col_kitchen else 0)
            floor   = parse_floor(row.get(col_floor)   if col_floor   else 0)
            price      = parse_price(row.get(col_price)      if col_price      else 0)
            base_price = parse_price(row.get(col_base_price) if col_base_price else 0)

            finish = str(row.get(col_finish, '')).strip() if col_finish else ''
            if finish.lower() in ('nan', '—', '-', ''): finish = ''

            district = str(row.get(col_district, '')).strip() if col_district else ''
            if district.lower() in ('nan', '—', '-', ''): district = ''
            # Нормализуем: убираем " р-н", " район", областные суффиксы ", ЛО" и т.п.
            if district:
                district = re.sub(r',?\s*(р-н|район)\s*', ' ', district, flags=re.IGNORECASE).strip()
                district = re.sub(r',?\s*(ЛО|МО|СПб|Ленинградская обл\.?)\s*$', '', district, flags=re.IGNORECASE).strip()
                district = district.strip(' ,')
            # Исключаем Всеволожский — нет на карте
            if district.lower() == 'всеволожский':
                continue

            jk = str(row.get(col_jk, '')).strip() if col_jk else ''
            if jk.lower() in ('nan', '', 'none'): jk = ''

            developer = str(row.get(col_developer, '')).strip() if col_developer else ''
            if developer.lower() in ('nan', '', 'none'): developer = ''

            status = str(row.get(col_status, '')).strip() if col_status else ''
            if status.lower() in ('nan', '', 'none'): status = ''
            on_request = 'запрос' in status.lower()
            booked     = 'брон' in status.lower()

            deadline = str(row.get(col_deadline, '')).strip() if col_deadline else ''
            if deadline.lower() in ('nan', '', 'none'): deadline = ''

            view = str(row.get(col_view, '')).strip() if col_view else ''
            if view.lower() in ('nan', '', 'none'): view = ''

            # Путь к планировке: пробуем .png и .jpg
            layout_name = str(row.get(col_layout, '')).strip() if col_layout else ''
            if layout_name.lower() in ('nan', '', 'none'): layout_name = ''

            def folder_name(s):
                """Приводим название ЖК к имени папки: убираем / и спецсимволы"""
                return re.sub(r'[/\\]', '', s).strip()

            if layout_name and jk:
                jk_enc = urllib.parse.quote(folder_name(jk), safe='')
                name_enc = urllib.parse.quote(layout_name, safe='')
                img_path = f"{CLOUD_BASE}/layouts/{jk_enc}/{name_enc}.webp"
            elif layout_name:
                img_path = f"{CLOUD_BASE}/layouts/{urllib.parse.quote(layout_name, safe='')}.webp"
            else:
                img_path = ''

            renders_url       = f"{CLOUD_BASE}/renders/{urllib.parse.quote(folder_name(jk), safe='')}" if jk else ''
            renders_thumb_url = f"{CLOUD_BASE}/renders-thumb/{urllib.parse.quote(folder_name(jk), safe='')}" if jk else ''

            # Считаем реальное кол-во рендеров из локальной папки
            renders_count = 0
            if jk:
                local_renders = BASE_DIR / "renders" / folder_name(jk)
                if local_renders.exists():
                    renders_count = len([f for f in local_renders.iterdir() if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')])

            apt_num = str(row.get(col_num, i)).strip() if col_num else str(i)

            # Вознаграждение — проверяем >= 4%
            hoff_gift = False
            if col_reward:
                reward_raw = str(row.get(col_reward, '')).strip()
                reward_num = re.findall(r'(\d+[.,]?\d*)', reward_raw)
                if reward_num:
                    try:
                        hoff_gift = float(reward_num[0].replace(',', '.')) >= 4
                    except:
                        pass

            # Рассрочки и ипотека из Google Sheets
            # Берём ипотеку и рассрочки из jk_data.json
            jk_info      = jk_data_all.get(jk, {})
            installments = jk_info.get("installments", [])
            mortgage     = jk_info.get("mortgage", [])
            if i <= 3:
                print(f"[DEBUG apt {i}] jk={jk!r} dev={developer!r} inst={len(installments)} mort={mortgage}")

            # Считаем реальную скидку из базовой цены
            # Санитарная проверка: базовая не должна превышать цену 100% более чем на 50%
            base_valid = (base_price > 0 and price > 0
                          and base_price > price
                          and base_price <= price * 1.5)
            has_discount = base_valid
            discount_pct = round((base_price - price) / base_price * 100) if has_discount else 0

            apartments.append({
                "id": f"apt_{i}", "num": apt_num,
                "r": r_raw, "rd": r_display,
                "a": area, "k": kitchen, "f": floor,
                "p": price, "ps": fmt_price(price),
                "pb": base_price, "pbs": fmt_price(base_price) if has_discount else "",
                "disc": discount_pct,
                "finish": finish, "district": district, "view": view,
                "img": img_path,
                "jk": jk,
                "deadline": deadline,
                "renders": renders_url,
                "renders_thumb": renders_thumb_url,
                "renders_count": renders_count,
                "installments": installments,
                "mortgage": mortgage,
                "hoff": hoff_gift,
                "onreq": on_request,
                "booked": booked,
                "dev": developer,
                "jk_about": jk_data_all.get(jk, {}).get("about", ""),
                "jk_features": jk_data_all.get(jk, {}).get("features", []),
                "jk_promo": jk_data_all.get(jk, {}).get("promo", []),
            })
        except Exception as e:
            print(f"  ⚠️  Строка {i}: {e}")
            continue

    # Типы
    type_map = {}
    for a in apartments:
        if a['r'] not in type_map:
            type_map[a['r']] = a['rd']
    order = {'0': 0, '1': 1, '2': 2, '3': 3, '4plus': 4, 'free': 5}
    type_order = sorted(type_map.keys(), key=lambda x: order.get(x, 99))
    room_types = [(k, type_map[k]) for k in type_order]

    finishes  = sorted(set(a['finish']   for a in apartments if a['finish']))
    districts = sorted(set(a['district'] for a in apartments if a['district']))

    # Диапазоны слайдеров
    ranges = {
        'a': slider_range(apartments, 'a'),
        'p': slider_range(apartments, 'p'),
    }

    print(f"\n✅ Квартир: {len(apartments)}")
    print(f"   Типы:    {room_types}")
    print(f"   Отделки: {finishes}")
    print(f"\n📐 Диапазоны слайдеров:")
    for key, r in ranges.items():
        nl = "нелинейный ⚡" if r['nonlinear'] else "линейный"
        print(f"   {key}: {r['min']:,.0f} – {r['max']:,.0f}  "
              f"(80% шкалы до {r['break80']:,.0f})  [{nl}]")

    return apartments, room_types, finishes, districts, ranges

# ──────────────────────────────────────────────
# HTML-БЛОКИ
# ──────────────────────────────────────────────
def room_btns_desktop(room_types):
    html = '<div class="room-btn active" data-room="all">Все</div>\n'
    for key, label in room_types:
        html += f'<div class="room-btn" data-room="{key}">{label}</div>\n'
    return html

def room_btns_mobile(room_types):
    short = {'0': 'Ст', '1': '1', '2': '2', '3': '3', '4plus': '4+', 'free': 'Своб.'}
    html = '<div class="m-segment-btn m-room-btn active" data-room="all">Все</div>\n'
    for key, label in room_types:
        sl = short.get(key, label[:3])
        html += f'<div class="m-segment-btn m-room-btn" data-room="{key}">{sl}</div>\n'
    return html

def finish_chips_desktop(finishes, prefix):
    if not finishes:
        return '<span style="color:#aaa;font-size:14px">Нет данных об отделке</span>'
    html = ''
    for f in finishes:
        safe = f.replace('"', '&quot;')
        html += (f'<label class="main-tower-cb-wrapper">'
                 f'<input type="checkbox" class="finish-cb {prefix}-finish-cb" value="{safe}">'
                 f'<span class="main-tower-custom"></span>'
                 f'<span class="main-tower-label-text">{f}</span></label>\n')
    return html

def finish_chips_mobile(finishes, prefix):
    if not finishes:
        return '<span style="color:#aaa;font-size:14px">Нет данных</span>'

    # PNG иконки для отделки — загружаются с GitHub
    ICON_SRC = {
        'safety': 'https://raw.githubusercontent.com/mishamixlay-ops/icons/main/safety_137285.webp',
        'wall':   'https://raw.githubusercontent.com/mishamixlay-ops/icons/main/wall_11404447.webp',
        'sofa':   'https://raw.githubusercontent.com/mishamixlay-ops/icons/main/sofa_6489690.webp',
        'shovel': 'https://raw.githubusercontent.com/mishamixlay-ops/icons/main/shovel_15806123.webp',
    }
        # SVG пунктир для "Без стен" — остаётся контурным
    SVG_NO_WALLS = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
                    ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
                    '<rect x="3" y="3" width="18" height="18" rx="2" stroke-dasharray="4 3"/></svg>')

    def get_icon(name):
        nl = name.lower()
        if 'стен' in nl or 'перегород' in nl:
            # Пунктирный SVG — меняет цвет через stroke="currentColor"
            return SVG_NO_WALLS
        elif 'без' in nl:
            return f'<img src="{ICON_SRC["wall"]}"   class="finish-icon-img" width="18" height="18">'
        elif 'подчист' in nl or 'предчист' in nl:
            return f'<img src="{ICON_SRC["shovel"]}" class="finish-icon-img" width="18" height="18">'
        elif 'мебел' in nl or 'мягк' in nl:
            return f'<img src="{ICON_SRC["sofa"]}"   class="finish-icon-img" width="18" height="18">'
        elif 'чист' in nl:
            return f'<img src="{ICON_SRC["safety"]}" class="finish-icon-img" width="18" height="18">'
        else:
            return ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
                    ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
                    '<polyline points="20 6 9 17 4 12"/></svg>')

    html = ''
    for f in finishes:
        safe = f.replace('"', '&quot;')
        icon = get_icon(f)
        html += (f'<label class="m-chip-btn m-finish-btn">'
                 f'<input type="checkbox" class="finish-cb {prefix}-finish-cb" value="{safe}">'
                 f'<span class="m-feature-icon">{icon}</span>{f}</label>\n')
    return html

# ──────────────────────────────────────────────
# PRE-RENDER: карточки генерируются Python-ом
# ──────────────────────────────────────────────
def render_card_html(apt, visible=True):
    """Генерирует HTML карточки — полный аналог JS renderCard()."""
    img_src = apt.get('img', '')
    if img_src:
        img_html = (f'<img src="{img_src}" class="apt-plan" loading="lazy"'
                    f' alt="Планировка" onload="this.classList.add(\'loaded\')"'
                    f' onerror="tryAltExt(this)">')
    else:
        img_html = '<div class="no-plan">Нет планировки</div>'

    has_discount = apt.get('disc', 0) > 0 and apt.get('pb', 0) > 0
    discount_pct = apt.get('disc', 0)
    old_price_html = f'<div class="apt-old-price">{apt["pbs"]}</div>' if has_discount else ''
    badge_html     = f'<div class="apt-discount-badge">-{discount_pct}%</div>' if has_discount else ''

    district_html = f'<div class="apt-district">{apt["district"]}</div>' if apt.get('district') else ''

    is_on_req = bool(apt.get('onreq'))
    is_booked = bool(apt.get('booked'))

    if is_on_req:
        price_html = (
            '<div class="apc-onreq-badge" onclick="_onReqTip(this)">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">'
            '<circle cx="12" cy="12" r="10"/>'
            '<line x1="12" y1="8" x2="12" y2="12"/>'
            '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
            'Под запрос'
            '<div class="apc-onreq-tooltip">Квартира может быть выведена в продажу застройщиком'
            ' по запросу. Цена может измениться.</div></div>'
        )
    else:
        price_html = f'<div class="apt-price">{apt["ps"]}</div>{old_price_html}'

    # Рендеры
    renders_count = apt.get('renders_count', 0)
    renders_base  = apt.get('renders_thumb') or apt.get('renders') or ''
    renders = [f"{renders_base}/{ri:03d}.webp"
               for ri in range(1, min(renders_count, 10) + 1)] if renders_base and renders_count else []

    total_slides = 1 + len(renders)

    dots_html = ''
    if total_slides > 1:
        for di in range(total_slides):
            active = ' active' if di == 0 else ''
            dots_html += f'<span class="apt-dot{active}" data-idx="{di}"></span>'

    dots_layer  = (f'<div class="apt-dots-layer"><div class="apt-dots-inner">{dots_html}</div></div>'
                   if total_slides > 1 else '')
    strip_class = ' apt-plan-strip--booked' if is_booked else ''
    strip_text  = 'В брони' if is_booked else ''
    renders_str = ','.join(renders)

    # data-* атрибуты для JS-фильтра
    finish_safe   = apt.get('finish',   '').replace('"', '&quot;')
    district_safe = apt.get('district', '').replace('"', '&quot;')
    onreq_val     = '1' if is_on_req else '0'
    booked_val    = '1' if is_booked else '0'
    display_attr  = '' if visible else ' style="display:none"'

    return (
        f'<div class="apt-card" data-apt-id="{apt["id"]}"'
        f' data-r="{apt["r"]}" data-p="{int(apt["p"])}" data-a="{apt["a"]}"'
        f' data-finish="{finish_safe}" data-district="{district_safe}"'
        f' data-onreq="{onreq_val}" data-booked="{booked_val}"{display_attr}>'
        f'<div class="apt-plan-wrapper" data-slide="0" data-total="{total_slides}"'
        f' data-renders="{renders_str}"'
        f' ontouchstart="aptSwipeStart(event)" ontouchmove="aptSwipeMove(event)"'
        f' ontouchend="aptSwipeEnd(event,this)"'
        f' onmousedown="aptSwipeStart(event)" onmouseup="aptSwipeEnd(event,this)"'
        f' style="user-select:none">'
        f'<div class="apt-render-overlay"></div>{badge_html}'
        f'<div class="apt-heart-zone">'
        f'<button class="apt-heart" onclick="toggleHeart(this,event)">'
        f'<svg viewBox="0 0 24 24"><path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3'
        f' 5 5 0 0 1 9 3c0 6-9 13-9 13z" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg></button></div>'
        f'<div class="apt-plan-photo">{img_html}</div>'
        f'{dots_layer}'
        f'<div class="apt-plan-strip{strip_class}">{strip_text}</div>'
        f'</div>'
        f'<div class="apt-info">'
        f'<div class="apt-price-row">{price_html}</div>'
        f'<div class="apt-type-area">{apt["rd"]}, {apt["a"]} м²</div>'
        f'{district_html}'
        f'</div>'
        f'</div>'
    )


# ──────────────────────────────────────────────
# БЫСТРЫЕ КАТЕГОРИИ — вспомогательные функции
# ──────────────────────────────────────────────
_WATER_DISTRICTS = {
    'Петроградский', 'Василеостровский', 'Курортный',
    'Кронштадтский', 'Адмиралтейский', 'Петродворцовый'
}

def _parse_firstpay(v):
    m = re.search(r'(\d+)', str(v or ''))
    return int(m.group(1)) if m else 999

def _is_long_term_install(term):
    s = str(term or '').lower()
    if re.search(r'202[7-9]|203\d', s): return True
    m = re.search(r'(\d+)\s*(?:лет|года|год)', s)
    if m and int(m.group(1)) >= 2: return True
    m = re.search(r'(\d+)\s*мес', s)
    if m and int(m.group(1)) >= 24: return True
    return False

def _apt_has_good_install(apt):
    """ПВ ≤ 20% + срок 2+ года + ключи до погашения."""
    for i in apt.get('installments', []):
        if (_parse_firstpay(i.get('firstpay', '')) <= 20
                and _is_long_term_install(i.get('term', ''))
                and i.get('keys_before_full_payment') == 'Да'):
            return True
    return False

def _diverse_top(pool, n=7):
    """
    Выбирает n квартир из pool с уникальными ЖК и разными ценовыми категориями.
    Сортирует итог по цене возрастанию.
    """
    if not pool:
        return []
    # Сортируем по цене
    sorted_pool = sorted(pool, key=lambda x: x.get('p', float('inf')))
    seen_jk = set()
    selected = []
    # Первый проход — берём по одной от каждого ЖК
    for a in sorted_pool:
        if a.get('jk', '') not in seen_jk:
            seen_jk.add(a.get('jk', ''))
            selected.append(a)
        if len(selected) >= n:
            break
    # Если не набрали n — добираем из оставшихся
    if len(selected) < n:
        for a in sorted_pool:
            if a not in selected:
                selected.append(a)
            if len(selected) >= n:
                break
    # Финальная сортировка по цене
    return sorted(selected, key=lambda x: x.get('p', float('inf')))


def _build_qc_data(apartments, base_url):
    """Вычисляет топ-7 квартир для каждой быстрой категории."""
    CAT_SIZE = 7

    # 1. Предложения месяца — топ по скидке, разные ЖК, по цене
    deals_pool = sorted([a for a in apartments if a.get('disc', 0) > 0],
                        key=lambda x: (-x['disc'], x.get('p', float('inf'))))
    deals_sel  = _diverse_top(deals_pool, CAT_SIZE)
    deals_ids  = [a['id'] for a in deals_sel]
    max_disc   = max((a['disc'] for a in apartments if a.get('disc', 0) > 0), default=0)

    # 2. Виды на воду — Нева и залив по полю view, fallback на район
    _water_kw = ['нев', 'залив', 'финск', 'море', 'морск']
    water_pool = [a for a in apartments
                  if any(kw in a.get('view', '').lower() for kw in _water_kw)]
    if len(water_pool) < 3:
        # Fallback — берём по району если данных по виду мало
        water_pool = [a for a in apartments if a.get('district', '') in _WATER_DISTRICTS]
    water_sel = _diverse_top(water_pool, CAT_SIZE)
    water_ids = [a['id'] for a in water_sel]

    # 3. Выгодные рассрочки — скор: (100−ПВ) + бонусы за ключи и срок
    def inst_score(apt):
        best = 0
        for i in apt.get('installments', []):
            pv   = _parse_firstpay(i.get('firstpay', ''))
            keys = i.get('keys_before_full_payment') == 'Да'
            long = _is_long_term_install(i.get('term', ''))
            s    = max(0, 100 - pv) + (25 if keys else 0) + (15 if long else 0)
            best = max(best, s)
        return best
    inst_pool = sorted(
        [a for a in apartments if inst_score(a) > 0],
        key=lambda x: -inst_score(x)
    )
    inst_sel  = _diverse_top(inst_pool, CAT_SIZE)
    inst_ids  = [a['id'] for a in inst_sel]

    # 4. Готово к заселению — "Сдан" в deadline
    ready_pool = [a for a in apartments if 'сдан' in a.get('deadline', '').lower()]
    ready_sel  = _diverse_top(ready_pool, CAT_SIZE)
    ready_ids  = [a['id'] for a in ready_sel]

    def enc(ru):
        return urllib.parse.quote(ru, safe='')

    return json.dumps([
        {'key': 'discount',
         'title': 'Предложения месяца',
         'tag': f'до\u00a0\u2212{max_disc}%',
         'sub': f'{len(deals_ids)}\u00a0квартир · скидки от застройщика',
         'img': f'{base_url}/{enc("Предложения_месяца")}.webp',
         'ids': deals_ids},
        {'key': 'water',
         'title': 'Лучшие виды на воду',
         'tag': 'Вода рядом',
         'sub': f'{len(water_ids)}\u00a0квартир · Петроградский, ВО и др.',
         'img': f'{base_url}/{enc("Виды_на_воду")}.webp',
         'ids': water_ids},
        {'key': 'installment',
         'title': 'Выгодные рассрочки',
         'tag': 'от 10% ПВ',
         'sub': f'{len(inst_ids)}\u00a0квартир · ключи до выплаты',
         'img': f'{base_url}/{enc("Рассрочки")}.webp',
         'ids': inst_ids},
        {'key': 'ready',
         'title': 'Готово к заселению',
         'tag': 'Уже сдан',
         'sub': f'{len(ready_ids)}\u00a0квартир · без рисков стройки',
         'img': f'{base_url}/{enc("Готово_к_заселению")}.webp',
         'ids': ready_ids},
    ], ensure_ascii=False)


# ──────────────────────────────────────────────
# ГЕНЕРАЦИЯ HTML
# ──────────────────────────────────────────────
def generate_html(apartments, room_types, finishes, districts, ranges):

    json_data      = json.dumps(apartments, ensure_ascii=False)
    json_room_types = json.dumps([[k, v] for k, v in room_types], ensure_ascii=False)
    json_finishes  = json.dumps(finishes,   ensure_ascii=False)
    json_districts = json.dumps(districts,  ensure_ascii=False)
    json_ranges    = json.dumps(ranges,     ensure_ascii=False)

    # ── Pre-render карточек ───────────────────────────────────────
    # Сортируем по цене asc — совпадает с дефолтной сортировкой JS,
    # чтобы пользователь видел правильный порядок мгновенно, до запуска JS
    INITIAL_SHOW = 8
    sorted_apts = sorted(apartments, key=lambda a: a['p'] if a['p'] > 0 else float('inf'))
    cards_html = '\n'.join(
        render_card_html(apt, visible=(i < INITIAL_SHOW))
        for i, apt in enumerate(sorted_apts)
    )
    print(f"   ✅ Pre-rendered карточек: {len(sorted_apts)} ({INITIAL_SHOW} visible, остальные hidden)")

    # ── Быстрые категории ─────────────────────────────────────────
    qc_data = _build_qc_data(apartments, YANDEX_CLOUD_BASE_URL)
    print(f"   ✅ Быстрые подборки сформированы")

    d_rooms  = room_btns_desktop(room_types)
    m_rooms  = room_btns_mobile(room_types)
    d_fin    = finish_chips_desktop(finishes, 'd')
    dm_fin   = finish_chips_desktop(finishes, 'd-modal')
    m_fin    = finish_chips_mobile(finishes,  'm')
    mi_fin   = finish_chips_mobile(finishes,  'm-inline')

    css = """:root {
--bg:#ffffff; --text:#162138; --muted:#9a9b9e;
--gold:#CBA363; --border:#e0e0e0; --hover:#214357;
--m-bg-gray:#F2F2F7; --tag-bg:#F0EBE5; --tag-text:#595046;
}
* { box-sizing:border-box; }
body { margin:0; padding:0; font-family:'Inter Tight',sans-serif; background:var(--bg); color:var(--text); -webkit-tap-highlight-color:transparent; }
.hidden-desktop { display:none !important; }
.hidden-mobile  { display:block !important; }
@media(max-width:900px) { .hidden-desktop{display:flex !important;} .hidden-mobile{display:none !important;} }
.real-estate-filter { width:100%; padding:40px 5%; }
@media(max-width:900px) { .real-estate-filter{padding:20px 15px;} }
.apartments-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:20px; margin-top:40px; }
@media(max-width:1300px) { .apartments-grid{grid-template-columns:repeat(3,1fr);} }
@media(max-width:900px)  { .apartments-grid{grid-template-columns:repeat(2,1fr); gap:10px; margin-top:20px;} }
@media(max-width:900px)  { .apartments-grid{grid-template-columns:repeat(2,1fr); column-gap:3px; row-gap:16px; margin-top:16px;} .apt-card:nth-child(odd) .apt-info{padding-left:15px;} .apt-card:nth-child(even) .apt-info{padding-right:15px;} }
.apt-card { background:#fff; border-radius:0; overflow:hidden; display:flex; flex-direction:column; transition:0.3s; cursor:pointer; }
.apt-plan-wrapper { width:100%; display:flex; flex-direction:column; overflow:hidden; background:linear-gradient(to bottom,#f7f7f7 0%,#f8f8f8 100%); border:none; border-radius:0; position:relative; }
.apt-heart-zone { height:42px; flex-shrink:0; background:transparent; display:flex; align-items:flex-end; justify-content:space-between; padding-right:12px; padding-left:0; padding-bottom:2px; }
.apt-plan-photo { flex:0 0 auto; aspect-ratio:1/1; width:100%; overflow:hidden; position:relative; background:linear-gradient(to bottom,#f7f7f7 0%,#f8f8f8 100%); }
.apt-plan { width:100%; height:100%; object-fit:contain; opacity:0; transition:opacity 0.3s; cursor:zoom-in; mix-blend-mode:multiply; padding:10px; box-sizing:border-box; }
.apt-plan.loaded { opacity:1; }
.no-plan { width:100%; height:100%; display:flex; align-items:center; justify-content:center; color:#ccc; font-size:13px; }
.apt-discount-badge { position:absolute; top:0; left:0; z-index:2; background:#e8244b; color:#fff; font-size:12px; font-weight:600; padding:4px 8px; border-radius:0 0 8px 0; z-index:2; }
@media(max-width:900px) { .apt-discount-badge{font-size:11px; padding:3px 6px;} }
.apt-plan-strip { flex-shrink:0; height:22px; background:transparent; display:flex; align-items:center; justify-content:center; }
.apt-plan-strip--booked { background:#e8e8e6; color:#3a3a3a; font-size:11px; font-weight:400; letter-spacing:0.04em; }
/* Слайдер карточки */
.apt-slider { position:relative; width:100%; overflow:hidden; }
.apt-slides { display:flex; flex-direction:row; flex-wrap:nowrap; transition:transform 0.3s ease; width:100%; height:100%; }
.apt-slide { flex:0 0 100%; width:100%; height:100%; position:relative; }
.apt-slide-render { width:100%; height:100%; object-fit:cover; display:block; background:#eee; }
/* Точки — отдельный тонкий слой между планировкой и бронью */
.apt-dots-layer { flex-shrink:0; height:16px; display:flex; align-items:center; justify-content:flex-end; padding-right:10px; }
.apt-dots-inner { display:flex; gap:4px; align-items:center; }
.apt-dot { width:4px; height:4px; border-radius:50%; background:rgba(0,0,0,0.2); transition:all 0.25s; }
.apt-dot.active { background:rgba(0,0,0,0.55); }
.apt-plan-wrapper { position:relative; }
/* Оверлей рендера — поверх всех зон */
.apt-render-overlay { display:none; position:absolute; inset:0; z-index:10; background-size:cover; background-position:center; pointer-events:none; }
.apt-dots-layer { z-index:12; position:relative; }
.apt-plan-strip { z-index:12; position:relative; }
.apt-plan-wrapper.show-render .apt-dot { background:rgba(255,255,255,0.5); }
.apt-plan-wrapper.show-render .apt-dot.active { background:#fff; }
.apt-plan-wrapper.show-render .apt-plan-strip--booked { background:rgba(0,0,0,0.3) !important; color:#fff !important; }
@media(max-width:900px) { .apt-booked-badge{font-size:11px; padding:3px 6px;} }
.fav-toast { position:fixed; top:-60px; left:12px; right:12px; transform:none; background:rgba(140,140,140,0.88); color:#fff; font-size:15px; font-weight:400; padding:10px 20px; border-radius:50px; z-index:999; display:flex; align-items:center; justify-content:center; gap:10px; transition:top 0.35s cubic-bezier(0.23,1,0.32,1); pointer-events:none; }
/* Быстрые подборки */
.qc-section{background:#fff;padding:44px 5% 48px;}
@media(max-width:900px){.qc-section{padding:28px 15px 32px;}}
.qc-inner{max-width:1400px;margin:0 auto;}
.qc-label{font-size:11px;letter-spacing:.1em;color:#bbb;text-transform:uppercase;margin:0 0 16px;}
.qc-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
@media(max-width:1100px){.qc-grid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:900px){.qc-grid{grid-template-columns:repeat(2,1fr);gap:8px;}}
.qc-tile{position:relative;aspect-ratio:1/1;border-radius:14px;overflow:hidden;cursor:pointer;-webkit-tap-highlight-color:transparent;}
.qc-tile img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;transition:transform .5s cubic-bezier(.25,1,.5,1);}
.qc-tile:hover img{transform:scale(1.05);}
.qc-ov{position:absolute;inset:0;background:linear-gradient(to top,rgba(8,10,15,.78) 0%,rgba(8,10,15,.12) 55%,transparent 100%);}
.qc-tag{position:absolute;top:12px;left:12px;background:#CBA363;color:#0d1117;font-size:10px;font-weight:700;padding:3px 9px;border-radius:20px;letter-spacing:.04em;white-space:nowrap;}
.qc-body{position:absolute;bottom:14px;left:14px;right:40px;}
.qc-title{font-size:14px;font-weight:600;color:#fff;line-height:1.3;margin:0 0 3px;}
.qc-sub{font-size:11px;color:rgba(255,255,255,.55);line-height:1.4;}
@media(max-width:900px){.qc-title{font-size:13px;}.qc-sub{font-size:10px;}}
.qc-arr{position:absolute;bottom:12px;right:12px;width:26px;height:26px;border-radius:50%;background:rgba(255,255,255,.18);display:flex;align-items:center;justify-content:center;}
.qc-arr svg{width:11px;height:11px;stroke:#fff;fill:none;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;}
/* Баннер активной подборки */
.qc-banner{display:none;align-items:center;gap:10px;background:#162138;color:#fff;padding:10px 16px;border-radius:10px;margin-bottom:16px;}
.qc-banner.visible{display:flex;}
.qc-banner-text{flex:1;font-size:13px;font-weight:500;}
.qc-banner-reset{background:none;border:1px solid rgba(255,255,255,.3);color:rgba(255,255,255,.85);border-radius:20px;padding:5px 14px;font-size:12px;cursor:pointer;font-family:'Inter Tight',sans-serif;white-space:nowrap;transition:.2s;}
.qc-banner-reset:hover{border-color:#CBA363;color:#CBA363;}
.fav-toast.visible { top:70px; }
.fav-toast svg { width:18px; height:18px; stroke:#fff; fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; }
.fav-panel-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:3999; }
.fav-panel-overlay.open { display:block; }
.fav-panel { position:fixed; top:0; right:0; bottom:0; width:100%; max-width:480px; background:#fff; z-index:4000; transform:translateX(100%); transition:transform 0.35s cubic-bezier(0.23,1,0.32,1); display:flex; flex-direction:column; }
.fav-panel.open { transform:translateX(0); }
.fav-panel-header { display:flex; align-items:center; justify-content:space-between; padding:16px 16px 12px; border-bottom:1px solid #f0f0f0; flex-shrink:0; }
.fav-panel-title { font-size:22px; font-weight:700; color:#1a1a1a; }
.fav-panel-count { font-size:16px; font-weight:400; color:#aaa; margin-left:8px; }
.fav-panel-close { width:36px; height:36px; border:none; background:#f5f5f5; border-radius:50%; cursor:pointer; display:flex; align-items:center; justify-content:center; font-size:18px; color:#555; }
.fav-panel-sort { display:flex; align-items:center; gap:6px; padding:10px 16px; border-bottom:1px solid #f0f0f0; flex-shrink:0; flex-wrap:wrap; }
.fav-sort-btn { font-size:13px; color:#888; background:#f5f5f5; border:none; border-radius:20px; padding:6px 14px; cursor:pointer; transition:0.2s; }
.fav-sort-btn.active { background:#1a1a1a; color:#fff; }
.fav-panel-list { flex:1; overflow-y:auto; padding:16px; }
.fav-item { display:flex; gap:14px; padding:20px 0; align-items:flex-start; cursor:pointer; }
.fav-item:last-child { border-bottom:none; }
.fav-item-img { width:168px; height:216px; border-radius:10px; background:#f5f5f5; flex-shrink:0; overflow:hidden; border:1px solid #e8e8e8; position:relative; display:flex; flex-direction:column; }
.fav-item-img-heart-zone { height:36px; flex-shrink:0; background:#f5f5f5; display:flex; align-items:flex-end; justify-content:flex-end; padding-right:6px; padding-bottom:4px; }
.fav-item-img-photo { flex:1; overflow:hidden; }
.fav-item-img-photo img { width:100%; height:100%; object-fit:contain; mix-blend-mode:multiply; padding:6px; box-sizing:border-box; }
.fav-item-heart { background:none; border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; padding:0; }
.fav-item-heart svg { width:18px; height:18px; stroke:#e8244b; fill:#e8244b; stroke-width:2; }
.fav-item-info { flex:1; min-width:0; display:flex; flex-direction:column; gap:6px; }
.fav-item-district { font-size:14px; color:#aaa; font-weight:300; }
.fav-item-type { font-size:14px; color:#555; font-weight:400; }
.fav-item-price { font-size:16px; font-weight:600; color:#1a1a1a; margin-top:4px; }
.fav-item-old-price { font-size:12px; color:#aaa; text-decoration:line-through; font-weight:400; margin-left:6px; }
.fav-item-btn { margin-top:10px; width:100%; padding:12px 0; background:var(--hover); border:none; border-radius:10px; font-size:12px; font-weight:500; color:#fff; cursor:pointer; text-align:center; letter-spacing:0.3px; font-family:'Inter Tight',sans-serif; transition:0.2s; }
.fav-item-btn:active { opacity:0.85; }
.fav-panel-sort-btn { width:36px; height:36px; background:#f5f5f5; border:none; border-radius:50%; cursor:pointer; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.fav-panel-sort-btn svg { width:18px; height:18px; stroke:#555; fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.fav-panel-empty { display:flex; align-items:center; justify-content:center; height:200px; color:#aaa; font-size:15px; }
.apt-heart { background:none; border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; padding:0; transition:transform 0.15s; margin-left:auto; }
.apt-heart:active { transform:scale(0.88); }

.apt-heart svg { width:18px; height:18px; stroke:#aaa; fill:none; stroke-width:2; transition:stroke 0.2s, fill 0.2s; }
.apt-heart.liked svg { stroke:#e8244b; fill:#e8244b; }
@keyframes heartPop { 0%{transform:scale(1)} 30%{transform:scale(1.45)} 60%{transform:scale(0.88)} 100%{transform:scale(1)} }
.apt-heart.pop { animation:heartPop 0.4s cubic-bezier(0.36,0.07,0.19,0.97); }
@keyframes heartParticle { 0%{opacity:1;transform:translate(-50%,-50%) scale(1)} 100%{opacity:0;transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy))) scale(0)} }
.heart-particle { position:absolute; pointer-events:none; width:6px; height:6px; border-radius:50%; background:#e8244b; animation:heartParticle 0.5s ease-out forwards; z-index:10; }
.apt-info { padding:10px 4px 14px; display:flex; flex-direction:column; gap:2px; }
.apt-price-row { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.apt-price { font-size:18px; font-weight:600; color:#1a1a1a; white-space:nowrap; }
.apt-old-price { font-size:14px; font-weight:400; color:#aaa; text-decoration:line-through; white-space:nowrap; }
.apt-type-area { font-size:14px; font-weight:400; color:#1a1a1a; }
.apt-district { font-size:13px; color:#888; font-weight:300; }

@media(max-width:900px) { .apt-price{font-size:15px;} .apt-old-price{font-size:12px;} .apt-type-area{font-size:12px;} .apt-district{font-size:11px;} .apt-info{padding:8px 2px 10px;} }
.btn-primary { width:100%; padding:16px 0; display:block; text-transform:uppercase; font-size:13px; letter-spacing:1.5px; cursor:pointer; text-align:center; border-radius:8px; font-weight:500; transition:0.3s; background:#fff; color:var(--hover); border:1px solid var(--hover); margin-top:16px; }
.btn-primary:hover { background:var(--hover); color:#fff; }
.desktop-filter-container { margin-bottom:50px; }
.filter-top-row { display:flex; align-items:center; justify-content:center; gap:16px; margin-bottom:36px; flex-wrap:wrap; }
.district-btn { border:1px solid var(--border); background:#fff; padding:14px 28px; cursor:pointer; font-size:15px; font-weight:300; border-radius:6px; transition:0.3s; color:var(--text); white-space:nowrap; }
.district-btn:hover { background:#ebebeb; }
.main-room-selector { display:flex; gap:8px; flex-wrap:wrap; justify-content:center; }
.room-btn { border:1px solid var(--border); background:#fff; padding:12px 22px; cursor:pointer; font-size:14px; font-weight:300; text-transform:uppercase; border-radius:6px; transition:0.3s; color:var(--text); text-align:center; }
.room-btn.active,.room-btn:hover { background:var(--gold); border-color:var(--gold); color:#fff; }
.desktop-modal-rooms .room-btn { padding:12px 22px; }
.sort-bar { display:flex; align-items:center; gap:12px; margin-bottom:10px; flex-wrap:wrap; }
.sort-label { font-size:12px; font-weight:300; letter-spacing:0.08em; color:var(--muted); white-space:nowrap; }
.sort-track { display:flex; gap:8px; flex-wrap:wrap; }
.sort-btn { border:1px solid var(--border); background:#fff; padding:8px 16px; cursor:pointer; font-size:12px; font-weight:300; letter-spacing:0.06em; border-radius:6px; transition:0.3s; color:var(--text); font-family:'Inter Tight',sans-serif; white-space:nowrap; }
.sort-btn.active { background:var(--gold); border-color:var(--gold); color:#fff; }
.sort-btn:hover:not(.active) { border-color:var(--text); }
@media(max-width:900px) {
  .sort-bar { flex-direction:column; align-items:stretch; gap:8px; background:#fff; border-radius:12px; border:1px solid transparent; padding:12px 20px; margin-bottom:12px; }
  .sort-label { font-size:13px; font-weight:400; color:#666; padding-left:4px; letter-spacing:0.5px; }
  .sort-track { background:var(--m-bg-gray); padding:4px; border-radius:100px; display:flex; justify-content:space-between; gap:1px; width:100%; box-sizing:border-box; flex-wrap:nowrap; }
  .sort-btn { flex:none; text-align:center; padding:9px 12px; font-size:13px; font-weight:300; color:#8E8E93; border-radius:100px; border:none; background:transparent; letter-spacing:0; white-space:nowrap; }
  .sort-btn.active { background:#fff; color:var(--hover); font-weight:600; box-shadow:0 4px 10px rgba(0,0,0,0.15); }
  .sort-btn:hover:not(.active) { border:none; background:transparent; }
}
.main-filters-row { display:flex; justify-content:center; gap:32px; margin-bottom:36px; padding:28px 0; border-top:1px solid #dcdcdc; border-bottom:1px solid #dcdcdc; flex-wrap:wrap; }
.main-filter-item { flex:1; min-width:240px; max-width:420px; }
.filter-label { display:flex; justify-content:space-between; margin-bottom:18px; font-size:14px; font-weight:300; text-transform:uppercase; color:var(--text); }
.filter-values { color:var(--gold); font-weight:400; }
.noUi-target { border:none; background:#e0e0e0; height:2px; box-shadow:none; }
.noUi-connect { background:var(--gold); }
.noUi-horizontal .noUi-handle { width:20px; height:20px; right:-10px; top:-9px; border-radius:50%; background:#fff; border:2px solid var(--gold); box-shadow:0 2px 5px rgba(0,0,0,0.1); cursor:grab; }
.noUi-handle:before,.noUi-handle:after { display:none; }
.main-towers-wrapper { display:flex; justify-content:center; gap:16px; margin-bottom:36px; flex-wrap:wrap; }
.main-tower-cb-wrapper { display:flex; align-items:center; gap:10px; cursor:pointer; padding:10px 18px; border-radius:8px; transition:0.2s; user-select:none; }
.main-tower-cb-wrapper:hover { background:#ebebeb; }
.main-tower-cb-wrapper input { display:none; }
.main-tower-custom { width:22px; height:22px; border:1px solid #ccc; border-radius:5px; display:flex; align-items:center; justify-content:center; background:#fff; transition:0.2s; flex-shrink:0; }
.main-tower-cb-wrapper input:checked + .main-tower-custom { background:var(--gold); border-color:var(--gold); }
.main-tower-cb-wrapper input:checked + .main-tower-custom:after { content:'✔'; color:#fff; font-size:13px; }
.main-tower-label-text { font-size:15px; font-weight:300; text-transform:uppercase; letter-spacing:0.8px; }
#floating-filter-btn { display:none !important; position:fixed; bottom:30px; left:50%; transform:translateX(-50%) translateY(20px); background:var(--text); color:#fff; padding:14px 28px; border-radius:30px; box-shadow:0 10px 30px rgba(0,0,0,0.3); cursor:pointer; font-size:15px; font-weight:400; text-transform:uppercase; letter-spacing:1px; z-index:1000; opacity:0; visibility:hidden; transition:0.3s; display:flex; align-items:center; gap:10px; white-space:nowrap; }
#floating-filter-btn.visible { opacity:1; visibility:visible; transform:translateX(-50%) translateY(0); }
#floating-filter-btn svg { fill:#fff; width:16px; height:16px; flex-shrink:0; }
/* Мобильная верхняя панель */
#mobile-top-bar { display:none; position:fixed; top:0; left:0; right:0; z-index:1000; background:#fff; padding:10px 16px 10px; box-shadow:0 1px 0 rgba(0,0,0,0.08); transform:translateY(-100%); transition:transform 0.35s cubic-bezier(0.23,1,0.32,1); }
#mobile-top-bar.visible { transform:translateY(0); }
@media(max-width:900px) { #mobile-top-bar { display:flex; align-items:center; gap:10px; } }
.mtb-inner { display:flex; align-items:center; width:100%; gap:10px; }
.mtb-icon-track { background:var(--m-bg-gray); padding:2px; border-radius:50%; display:flex; flex-shrink:0; border:2px solid transparent; transition:border-color 0.2s; }
#mtb-fav-track.has-favs { border-color:#e8244b; background:#fff3f5; }
.mtb-fav-badge { position:absolute; bottom:-4px; right:-4px; min-width:18px; height:18px; background:#e8244b; color:#fff; font-size:11px; font-weight:700; border-radius:9px; display:none; align-items:center; justify-content:center; padding:0 4px; box-sizing:border-box; border:2px solid #fff; }
.mtb-fav-badge.visible { display:flex; }
.mtb-icon-btn { width:36px; height:36px; border-radius:50%; border:none; background:transparent; display:flex; align-items:center; justify-content:center; cursor:pointer; transition:all 0.2s; color:#8E8E93; }
.mtb-icon-btn svg { width:22px; height:22px; fill:none; stroke:currentColor; stroke-width:1.8; transition:stroke 0.2s; }
.mtb-icon-btn.active { background:#fff !important; color:var(--hover) !important; box-shadow:0 4px 10px rgba(0,0,0,0.15) !important; stroke:var(--hover) !important; }
.mtb-icon-btn.active svg { stroke:var(--hover) !important; }
.mtb-center { flex:1; text-align:center; }
.mtb-count { font-size:15px; font-weight:500; color:#1a1a1a; }
.mtb-label { font-size:12px; color:#888; font-weight:300; margin-top:1px; }
.filter-popup-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); backdrop-filter:blur(5px); z-index:2000; opacity:0; transition:opacity 0.3s; }
.filter-popup-overlay.active { display:block; opacity:1; }
.filter-popup { position:fixed; z-index:2001; background:#fff; display:flex; flex-direction:column; box-shadow:0 10px 40px rgba(0,0,0,0.2); transform:translate3d(0,110%,0); transition:transform 0.5s cubic-bezier(0.23,1,0.32,1); will-change:transform; }
/* Sort popup */
#sort-popup-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4); z-index:3000; opacity:0; transition:opacity 0.3s; }
#sort-popup-overlay.active { display:block; opacity:1; }
#sort-popup { position:fixed; bottom:0; left:0; right:0; background:#fff; border-radius:20px 20px 0 0; z-index:3001; padding:24px 20px 40px; transform:translateY(100%); transition:transform 0.4s cubic-bezier(0.23,1,0.32,1); }
#sort-popup.active { transform:translateY(0); }
.sort-popup-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
.sort-popup-title { font-size:17px; font-weight:600; color:#1a1a1a; }
.sort-popup-close { width:32px; height:32px; background:none; border:none; cursor:pointer; font-size:22px; color:#888; display:flex; align-items:center; justify-content:center; padding:0; }
.sort-popup-item { display:flex; align-items:center; justify-content:space-between; padding:16px 0; border-bottom:1px solid #f0f0f0; cursor:pointer; }
.sort-popup-item:last-child { border-bottom:none; }
.sort-popup-item-label { font-size:16px; font-weight:300; color:#1a1a1a; }
.sort-popup-radio { width:22px; height:22px; border-radius:50%; border:2px solid #d0d0d0; display:flex; align-items:center; justify-content:center; flex-shrink:0; transition:border-color 0.2s; }
.sort-popup-item.active .sort-popup-radio { border-color:#e8244b; }
.sort-popup-item.active .sort-popup-radio::after { content:''; width:10px; height:10px; border-radius:50%; background:#e8244b; }
.filter-popup.active { transform:translate3d(0,0,0) !important; }
@media(max-width:900px) {
.filter-popup { bottom:10px; left:10px; right:10px; width:calc(100% - 20px); height:85vh; border-radius:30px; overflow:visible !important; }
.m-header { padding:30px 20px 20px 20px !important; cursor:grab; touch-action:none; }
.m-handle { width:40px; height:4px; background:#E5E5EA; border-radius:2px; margin:0 auto 10px auto; }
}
@media(min-width:901px) {
.filter-popup { top:50%; left:50%; width:520px; height:auto; max-height:85vh; border-radius:24px; transform:translate(-50%,-50%) scale(0.95); opacity:0; visibility:hidden; }
.filter-popup.active { transform:translate(-50%,-50%) scale(1); opacity:1; visibility:visible; }
.m-handle { display:none; }
.m-header { padding:25px 30px !important; }
.m-content { padding:0 30px 30px 30px !important; }
.m-footer { position:static !important; padding:20px 30px 30px 30px !important; border-top:none !important; }
}
.m-header { display:flex; flex-direction:column; align-items:center; justify-content:center; position:relative; }
.m-title  { font-size:20px; font-weight:700; color:var(--text); text-align:left; width:100%; padding-left:10px; }
.m-back-btn { width:44px; height:44px; border-radius:50%; background:rgba(255,255,255,0.3); backdrop-filter:blur(8px); border:1px solid rgba(255,255,255,0.5); display:flex; align-items:center; justify-content:center; cursor:pointer; position:absolute; left:15px; top:-60px; z-index:2002; }
.m-back-btn svg { width:18px; height:18px; stroke:#fff; stroke-width:2.5; }
@media(min-width:901px) { .m-back-btn{position:static;background:#f2f2f2;border:none;width:32px;height:32px;} .m-back-btn svg{stroke:var(--text);} }
.m-content { padding:0 20px 80px 20px; overflow-y:auto; flex-grow:1; }
.m-section-label { font-size:13px; font-weight:400; color:#666; margin-bottom:10px; padding-left:4px; letter-spacing:0.5px; }
.m-block-spacer { margin-bottom:28px; }
.inline-mobile-filter { display:none; background:#fff; border-radius:12px; padding:20px; margin-bottom:28px; border:1px solid #e0e0e0; }
@media(max-width:900px) { .inline-mobile-filter{display:block;} }
.m-segment-track { background:var(--m-bg-gray); padding:4px; border-radius:100px; display:flex; gap:2px; overflow-x:auto; }
.m-segment-btn { flex:1; text-align:center; padding:9px 4px; font-size:13px; font-weight:300; color:#8E8E93; border-radius:100px; cursor:pointer; transition:all 0.2s; background:transparent; user-select:none; white-space:nowrap; min-width:36px; }
.m-segment-btn.active { background:#fff; color:var(--hover); font-weight:600; box-shadow:0 4px 10px rgba(0,0,0,0.15); }
.m-chips-track { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.m-chip-btn { display:flex; align-items:center; gap:8px; padding:11px 14px; font-size:13px; color:var(--text); background:#fff; border:1px solid #E5E5EA; border-radius:50px; cursor:pointer; transition:all 0.2s; user-select:none; }
.m-chip-btn.active { color:var(--hover); border-color:#fff; box-shadow:0 4px 10px rgba(0,0,0,0.15); font-weight:600; }
.m-chip-btn input { display:none; }
.m-feature-icon { color:#9a9b9e; display:flex; align-items:center; transition:0.2s; flex-shrink:0; }
.m-chip-btn.active .m-feature-icon { color:var(--gold) !important; }
.finish-icon-img { filter: brightness(0) opacity(0.45); transition: filter 0.2s; }
.m-chip-btn.active .finish-icon-img { filter: invert(72%) sepia(26%) saturate(687%) hue-rotate(358deg) brightness(96%) contrast(88%); }
.m-district-btn { width:100%; padding:14px 20px; background:#fff; border:1px solid var(--border); border-radius:50px; font-family:'Inter Tight',sans-serif; font-size:13px; font-weight:300; color:#8E8E93; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:8px; transition:0.2s; }
.m-district-btn:hover { background:#f5f5f5; }
.m-district-btn.has-selection { border-color:var(--gold); color:var(--gold); font-weight:500; }
/* MAP POPUP */
.map-popup-overlay { display:none; position:fixed; inset:0; background:rgba(180,175,170,0.35); backdrop-filter:blur(2px); -webkit-backdrop-filter:blur(2px); z-index:3000; align-items:flex-end; justify-content:center; }
.map-popup-overlay.active { display:flex; }
.map-popup { background:#ffffff; border-radius:20px; width:calc(100% - 20px); max-width:600px; margin:0 10px calc(10px + env(safe-area-inset-bottom, 16px)); height:calc(100dvh - 60px); display:flex; flex-direction:column; opacity:0; transform:translateY(40px); transition:opacity 0.4s ease, transform 0.45s cubic-bezier(0.23,1,0.32,1); pointer-events:none; overflow:hidden; position:relative; }
.map-popup.active { opacity:1; transform:translateY(0); pointer-events:all; }
.map-popup-header { position:absolute; top:0; left:0; right:0; display:flex; align-items:center; justify-content:space-between; padding:16px 18px 36px; background:linear-gradient(to bottom, #ffffff 50%, transparent 100%); z-index:15; pointer-events:none; }
.map-popup-title { font-size:15px; font-weight:500; color:#1a1a1a; letter-spacing:0.01em; pointer-events:auto; }
.map-popup-close { width:32px; height:32px; border-radius:0; background:none; border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:0.2s; flex-shrink:0; padding:0; pointer-events:auto; }
.map-popup-close:hover { opacity:0.5; }
.map-popup-close svg { width:20px; height:20px; stroke:#222; stroke-width:2.5; fill:none; }
.map-svg-wrap { flex:1; position:relative; display:flex; align-items:center; justify-content:center; min-height:0; overflow:hidden; background:#ffffff; padding-bottom:80px; padding-top:60px; }
.map-svg-wrap svg { height:100%; width:auto; display:block; max-width:100%; transform-origin:0 0; filter:drop-shadow(0 1px 6px rgba(0,0,0,0.09)); }
.map-svg-wrap svg.animating { animation: mapZoomIn 0.35s cubic-bezier(0.22,1,0.36,1) forwards; }
.map-svg-wrap::after { content:''; position:absolute; inset:0; pointer-events:none; background:radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.06) 100%); z-index:2; }
@keyframes mapZoomIn { from { opacity:0; transform:translate(var(--tx0),var(--ty0)) scale(var(--s0)); } to { opacity:1; transform:translate(var(--tx1),var(--ty1)) scale(var(--s1)); } }
@media (hover: none) { .map-district:not(.selected):hover { fill:#d9d9d9; } .map-district.hover { fill:#d9d9d9; } }

.map-compass { position:absolute !important; top:130px !important; right:12px; z-index:10; pointer-events:none; width:47px !important; height:47px !important; flex:none; }
.water-body { fill:#C8DFF0; stroke:none; pointer-events:none; }
.map-loading { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:rgba(0,0,0,0.25); font-size:12px; letter-spacing:0.15em; text-transform:uppercase; min-height:300px; }
.map-district { fill:#d9d9d9; stroke:#ffffff; stroke-width:1.5; cursor:pointer; transition:fill 0.2s; }
.map-district:hover, .map-district.hover { fill:#c8c8c8; }
.map-district.selected { fill:var(--gold); stroke:#ffffff; filter:none; }
.map-district.selected:hover, .map-district.selected.hover { fill:#d4aa6a; }
/* Нижняя панель — поверх карты, не сдвигает её */
.map-bottom-panel { position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to bottom, transparent 0%, #ffffff 28px); padding:36px 18px calc(16px + env(safe-area-inset-bottom)); display:flex; flex-direction:column; gap:10px; z-index:5; }
@media(min-width:901px) {
  .map-popup-overlay { align-items:center; }
  .map-popup { max-width:760px; height:88vh; max-height:800px; margin:0; transform:translateY(20px); overflow:hidden; }
  .map-popup-header { position:absolute; background:linear-gradient(to bottom, #ffffff 60%, transparent 100%); padding:14px 18px 40px; }
  .map-bottom-panel { position:absolute; background:linear-gradient(to top, #ffffff 60%, transparent 100%); padding:40px 18px 16px; }
  .map-svg-wrap { padding-top:0; padding-bottom:0; overflow:visible; }
  .map-svg-wrap svg { overflow:visible; }
  .map-compass { top:auto !important; bottom:100px !important; }
}
.map-selected-bar { display:none; align-items:flex-start; gap:8px; flex-wrap:wrap; }
.map-selected-bar.visible { display:flex; }
.map-selected-chip { background:rgba(203,163,99,0.12); color:#9a7840; border:1px solid rgba(203,163,99,0.35); border-radius:20px; padding:4px 12px; font-size:12px; font-weight:400; letter-spacing:0.04em; }
.map-reset-btn { background:none; border:none; padding:0; font-size:12px; color:rgba(0,0,0,0.3); cursor:pointer; font-family:'Inter Tight',sans-serif; text-decoration:underline; text-underline-offset:3px; transition:0.2s; white-space:nowrap; }
.map-reset-btn:hover { color:rgba(0,0,0,0.6); }
.map-apply-btn { width:100%; padding:14px; border:1px solid rgba(0,0,0,0.18); border-radius:50px; background:transparent; color:rgba(0,0,0,0.7); font-size:13px; font-weight:400; letter-spacing:0.08em; text-transform:uppercase; cursor:pointer; font-family:'Inter Tight',sans-serif; transition:0.25s; }
.map-apply-btn:hover { background:var(--gold); border-color:var(--gold); color:#fff; }
.m-footer { position:absolute; bottom:0; left:0; width:100%; padding:20px; box-sizing:border-box; display:flex; justify-content:center; }
.m-apply-btn { width:100%; padding:17px; border:1px solid var(--text); border-radius:30px; background:#fff; color:var(--text); font-size:16px; font-weight:600; cursor:pointer; }
.m-slider-row { margin-bottom:60px; position:relative; }
.m-slider-row:last-child { margin-bottom:68px; }
.m-slider-label-row { display:flex; justify-content:space-between; margin-bottom:10px; font-size:13px; color:#666; }
.m-slider-styled .noUi-target  { background:#F2F2F2; height:24px; border-radius:12px; border:none; padding:0 12px; }
.m-slider-styled .noUi-connect { background:#fff; height:16px; top:4px; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
.m-slider-styled .noUi-handle  { width:16px; height:16px; background:#fff; border-radius:50%; border:none; box-shadow:0 2px 4px rgba(0,0,0,0.25); cursor:grab; top:4px; right:-8px; z-index:10; }
.m-slider-styled .noUi-handle::after  { content:''; position:absolute; width:4px; height:4px; background:#162138; border-radius:50%; top:50%; left:50%; transform:translate(-50%,-50%); }
.m-slider-styled .noUi-handle::before { display:none; }
.m-slider-styled .noUi-tooltip { background:#162138; color:#fff; border-radius:20px; padding:6px 14px; font-size:13px; font-weight:600; border:none; border:1px solid rgba(255,255,255,0.2); bottom:auto; top:32px; left:50%; white-space:nowrap; z-index:20; box-shadow:0 4px 10px rgba(0,0,0,0.2); cursor:grab; display:flex; align-items:center; justify-content:center; gap:6px; transition:top 0.2s, background-color 0.2s, box-shadow 0.2s; }
.noUi-handle-lower .noUi-tooltip { transform:translateX(-50%); }
.noUi-handle-upper .noUi-tooltip { transform:translateX(-85%); }
.noUi-handle.noUi-active .noUi-tooltip { bottom:auto; top:-45px; transform:translateX(-50%); background:#000; box-shadow:0 8px 20px rgba(0,0,0,0.3); cursor:grabbing; }
.desktop-filter-modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); backdrop-filter:blur(5px); z-index:10000; align-items:center; justify-content:center; }
.desktop-filter-modal-overlay.active { display:flex; }
.desktop-filter-modal { background:var(--bg); border-radius:12px; padding:50px 60px; max-width:1100px; width:90%; max-height:90vh; overflow-y:auto; position:relative; box-shadow:0 20px 60px rgba(0,0,0,0.3); }
.desktop-modal-close { position:absolute; top:25px; right:25px; width:40px; height:40px; border-radius:50%; background:transparent; display:flex; align-items:center; justify-content:center; cursor:pointer; border:none; }
.desktop-modal-close:hover { background:rgba(0,0,0,0.05); }
.desktop-modal-close svg { width:24px; height:24px; stroke:var(--text); stroke-width:2; }
.desktop-modal-title { font-size:30px; font-weight:600; margin-bottom:36px; color:var(--text); text-align:center; }
.desktop-modal-rooms { display:flex; justify-content:center; gap:8px; margin-bottom:36px; flex-wrap:wrap; }
.desktop-modal-sliders { display:flex; justify-content:center; gap:32px; padding:28px 0; border-top:1px solid #dcdcdc; border-bottom:1px solid #dcdcdc; margin-bottom:36px; flex-wrap:wrap; }
.desktop-modal-slider-item { flex:1; max-width:300px; min-width:180px; }
.desktop-modal-features { display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin-bottom:36px; }
.desktop-modal-apply { width:100%; max-width:400px; margin:0 auto; padding:17px 0; display:block; text-transform:uppercase; font-size:14px; letter-spacing:1.5px; cursor:pointer; text-align:center; border-radius:8px; font-weight:500; transition:0.3s; background:#fff; color:var(--hover); border:1px solid var(--hover); }
.desktop-modal-apply:hover { background:var(--hover); color:#fff; }
@media(max-width:900px) { .desktop-filter-modal-overlay{display:none !important;} }
.load-more-wrapper { text-align:center; margin:40px 0; }
#load-more-btn { padding:14px 38px; background:transparent; border:1px solid var(--text); border-radius:8px; text-transform:uppercase; cursor:pointer; font-weight:300; font-size:14px; }
#no-results { display:none; text-align:center; padding:50px; color:var(--muted); grid-column:1/-1; }
.found-counter-wrapper { text-align:center; margin-bottom:28px; margin-top:20px; font-size:15px; font-weight:500; color:#1a1a1a; display:flex; align-items:baseline; justify-content:center; gap:5px; }
@media(max-width:900px) { .found-counter-wrapper { margin-top:16px; margin-bottom:24px; font-size:15px; font-weight:500; } .apartments-grid { margin-top:0; } }
.count-num { color:var(--gold); font-weight:700; font-size:22px; }
.img-modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.92); align-items:center; justify-content:center; z-index:9999; }
.img-modal-overlay.active { display:flex; }
.img-modal-img { max-width:95%; max-height:95%; object-fit:contain; }
.img-modal-close { position:absolute; top:20px; right:20px; color:#fff; font-size:40px; cursor:pointer; line-height:1; }
/* Full-screen apartment card */
#apt-card-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100vh; z-index:999999; background:#F2F2F7; flex-direction:column; overflow-y:auto; -webkit-overflow-scrolling:touch; }
#apt-card-overlay.active { display:flex; }
.apc-header { position:fixed; top:0; left:0; right:0; z-index:5010; display:flex; align-items:center; justify-content:space-between; padding:12px 16px; pointer-events:none; background:transparent; transition:background 0.4s ease; }
.apc-header-btn { width:40px; height:40px; border-radius:50%; background:rgba(255,255,255,0.9); border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; pointer-events:all; backdrop-filter:blur(6px); flex-shrink:0; }
.apc-header-btn svg { width:18px; height:18px; stroke:#1a1a1a; fill:none; stroke-width:2; stroke-linecap:round; }
.apc-header-right { display:flex; gap:8px; }
.apc-likes { font-size:11px; font-weight:600; color:#1a1a1a; margin-top:2px; }
.apc-plan-area { width:100%; aspect-ratio:4/5; background:#f8f8f8; flex-shrink:0; overflow:hidden; position:relative; cursor:zoom-in; }
.apc-slides { display:flex; flex-direction:row; flex-wrap:nowrap; width:100%; height:100%; transition:transform 0.35s cubic-bezier(0.25,1,0.5,1); will-change:transform; }
.apc-slide { flex:0 0 100%; width:100%; height:100%; display:flex; align-items:center; justify-content:center; background:#f8f8f8; overflow:hidden; box-sizing:border-box; }
.apc-slide img { width:100%; height:100%; object-fit:contain; mix-blend-mode:multiply; padding:88px 26px 35px; box-sizing:border-box; display:block; object-position:center center; }
.apc-slide.render img { object-fit:cover; mix-blend-mode:normal; padding:0; }
.apc-plan-placeholder { color:#ccc; font-size:13px; }
.apc-inline-dots { position:absolute; bottom:10px; left:50%; transform:translateX(-50%); display:flex; gap:5px; z-index:2; pointer-events:none; }
.apc-inline-dot { width:6px; height:6px; border-radius:50%; background:rgba(0,0,0,0.18); transition:background 0.4s; }
.apc-inline-dot.active { background:rgba(0,0,0,0.55); }
.apc-inline-dots.white .apc-inline-dot { background:rgba(255,255,255,0.5); }
.apc-inline-dots.white .apc-inline-dot.active { background:rgba(255,255,255,0.95); }
#apc-img-popup { display:none; position:fixed; inset:0; z-index:1000001; background:#fff; flex-direction:column; }
#apc-img-popup.active { display:flex; }
.apc-img-popup-header { display:flex; justify-content:space-between; align-items:center; padding:16px 16px 8px; flex-shrink:0; }
.apc-img-popup-dots { display:flex; gap:6px; align-items:center; justify-content:center; position:absolute; bottom:80px; left:0; right:0; pointer-events:none; }
.apc-img-popup-dot { width:7px; height:7px; border-radius:50%; background:#d0d0d0; transition:background 0.25s, transform 0.25s, width 0.25s; cursor:pointer; }
.apc-img-popup-dot.active { background:#1a1a1a; transform:scale(1.6); }
.apc-img-popup-close { width:36px; height:36px; border-radius:50%; background:#f5f5f5; border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.apc-img-popup-close svg { width:16px; height:16px; stroke:#333; fill:none; stroke-width:2; stroke-linecap:round; }
.apc-img-popup-slides { flex:1; overflow:hidden; position:relative; }
.apc-img-popup-track { display:flex; flex-direction:row; flex-wrap:nowrap; height:100%; min-height:200px; transition:transform 0.35s cubic-bezier(0.25,1,0.5,1); }
.apc-img-popup-slide { flex:0 0 100%; width:100%; height:100%; display:flex; align-items:center; justify-content:center; background:#fff; }
.apc-img-popup-slide img { max-width:100%; max-height:100%; object-fit:contain; mix-blend-mode:multiply; padding:12px; box-sizing:border-box; display:block; }
.apc-img-popup-slide.render img { max-width:100%; max-height:100%; object-fit:contain; mix-blend-mode:normal; padding:12px; }
.apc-gallery { display:flex; gap:8px; padding:10px 16px 4px; overflow-x:auto; flex-shrink:0; scrollbar-width:none; background:#fff; }
.apc-gallery::-webkit-scrollbar { display:none; }
.apc-gallery-thumb { width:64px; height:64px; border-radius:8px; border:2px solid #e8e8e8; background:#f5f5f5; flex-shrink:0; overflow:hidden; display:flex; align-items:center; justify-content:center; cursor:pointer; transition:border-color 0.2s; }
.apc-gallery-thumb img { width:100%; height:100%; object-fit:contain; mix-blend-mode:multiply; padding:4px; box-sizing:border-box; }
.apc-gallery-thumb.render img { object-fit:cover; mix-blend-mode:normal; padding:0; }
.apc-gallery-thumb.active { border-color:#8E8E93; }
.apc-dots { display:none; }
.apc-body { padding:16px 16px 85px; flex:1; background:#fff; }
.apc-badge-row { display:flex; align-items:center; gap:8px; margin-bottom:14px; }
.apc-discount-badge { background:#e8244b; color:#fff; font-size:12px; font-weight:700; padding:4px 10px; border-radius:6px; }
.apc-row { display:flex; justify-content:space-between; align-items:baseline; padding:10px 0; border-bottom:1px solid #f0f0f0; gap:8px; }
.apc-row:last-of-type { border-bottom:none; }
.apc-label { font-size:14px; color:#888; font-weight:300; }
.apc-view-label { color:#162138 !important; font-weight:500 !important; display:flex !important; align-items:center; }
.apc-value { font-size:14px; color:#1a1a1a; font-weight:400; text-align:right; }
.apc-district { font-size:14px; color:#888; font-weight:300; margin:14px 0; }
.apc-price-row { display:flex; flex-direction:column; align-items:flex-start; gap:4px; margin:16px 0 15px; }
.apc-price { font-size:22px; font-weight:600; color:#1a1a1a; white-space:nowrap; }
.apc-old-price { font-size:18px; color:#aaa; text-decoration:line-through; font-weight:300; }
.apc-footer { position:fixed; bottom:0; left:0; right:0; background:#fff; padding:12px 16px calc(12px + env(safe-area-inset-bottom)); border-top:1px solid #f0f0f0; z-index:5010; }
.apc-finance-block { margin-top:0; }
.apc-about-wrap { position:relative; margin:8px 0 4px; }
.apc-about-text { font-size:14px; color:#555; line-height:1.6; max-height:72px; overflow:hidden; transition:max-height 0.3s ease; }
.apc-about-text.expanded { max-height:1000px; }
.apc-about-fade { position:absolute; bottom:0; left:0; right:0; height:40px; background:linear-gradient(transparent, #fff); pointer-events:none; transition:opacity 0.3s; }
.apc-about-fade.hidden { opacity:0; }
.apc-about-more { font-size:13px; color:#c8a96e; cursor:pointer; margin-bottom:15px; margin-top:4px; padding-bottom:0; display:inline-block; }
.apc-promo-hidden { display:none !important; }
.apc-promo-hidden.visible { display:flex !important; }
.apc-inst-card.apc-promo-hidden.visible { display:block !important; }
.apc-finance-item.apc-promo-hidden.visible { display:grid !important; grid-template-columns:1fr 85px 110px; align-items:start; column-gap:12px; }
.apc-features-scroll { display:flex; gap:8px; overflow-x:auto; padding:4px 0 12px; scrollbar-width:none; }
.apc-features-scroll::-webkit-scrollbar { display:none; }
.apc-feature-card { flex:0 0 140px; border-radius:10px; overflow:hidden; background:#f5f5f5; }
.apc-feature-card img { width:100%; height:80px; object-fit:cover; display:block; }
.apc-feature-card-text { font-size:11px; color:#1a1a1a; padding:6px 8px; line-height:1.3; }
.apc-promo-list { display:flex; flex-direction:column; gap:8px; }
.apc-promo-card { cursor:pointer; }
.apc-promo-card-top { padding:10px 12px; background:#F2F2F7; border-radius:12px; transition:transform .3s cubic-bezier(.34,1.56,.64,1); transform-origin:center; }
.apc-promo-card.open .apc-promo-card-top { transform:scale(1.03); }
.apc-promo-card-head { display:flex; align-items:center; justify-content:space-between; }
.apc-promo-card-name { font-size:14px; font-weight:500; color:#1a1a1a; transition:transform .3s cubic-bezier(.34,1.56,.64,1); transform-origin:left center; display:inline-block; }
.apc-promo-card.open .apc-promo-card-name { transform:scale(1.08); }
.apc-promo-card-val { font-size:14px; font-weight:500; color:#8E8E93; margin-left:6px; }
.apc-promo-card-sub { font-size:12px; color:#8E8E93; margin-top:2px; }
.apc-promo-card-chevron { transition:transform 0.3s ease; flex-shrink:0; }
.apc-promo-card.open .apc-promo-card-chevron { transform:rotate(90deg); }
.apc-promo-card-drawer { display:grid; grid-template-rows:0fr; transition:grid-template-rows 0.42s cubic-bezier(.4,0,.2,1); }
.apc-promo-card.open .apc-promo-card-drawer { grid-template-rows:1fr; }
.apc-promo-card-drawer-inner { overflow:hidden; min-height:0; }
.apc-promo-card-body { margin-top:4px; padding:12px; background:#fff; border:1px solid #E5E5EA; border-radius:12px; }
.apc-promo-card-field { margin-bottom:8px; opacity:0; transform:translateX(-6px); }
.apc-promo-card.open .apc-promo-card-field { animation:apcStagger 0.4s forwards; }
.apc-promo-card.open .apc-promo-card-field:nth-child(1){ animation-delay:.08s; }
.apc-promo-card.open .apc-promo-card-field:nth-child(2){ animation-delay:.14s; }
.apc-promo-card.open .apc-promo-card-field:nth-child(3){ animation-delay:.20s; }
.apc-promo-card.open .apc-promo-card-field:nth-child(4){ animation-delay:.26s; }
.apc-promo-card.open .apc-promo-card-field:nth-child(5){ animation-delay:.32s; }
.apc-promo-card.open .apc-promo-card-field:nth-child(6){ animation-delay:.38s; }
.apc-promo-card.open .apc-promo-card-field:nth-child(7){ animation-delay:.44s; }
@keyframes apcStagger { to { opacity:1; transform:translateX(0); } }
.apc-promo-card-field:last-child { margin-bottom:0; }
.apc-promo-card-field-label { font-weight:600; color:#1a1a1a; font-size:13px; margin-bottom:2px; }
.apc-promo-card-field-value { font-weight:400; color:#555; font-size:13px; line-height:1.5; }
.apc-promo-card.apc-promo-extra { display:none; }
.apc-promo-card.apc-promo-extra.visible { display:block; }
.apc-promo-more { font-size:13px; color:#8E8E93; cursor:pointer; margin-top:14px; display:inline-block; }
.apc-promo-more::after { content:''; display:inline-block; width:6px; height:6px; border-right:1.5px solid #8E8E93; border-bottom:1.5px solid #8E8E93; transform:rotate(45deg); margin-left:5px; vertical-align:1px; transition:transform 0.3s; }
.apc-promo-more.expanded::after { transform:rotate(-135deg); vertical-align:-2px; }
.apc-promo-tooltip { display:none; position:absolute; left:0; top:calc(100% + 6px); width:280px; background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:10px 12px; font-size:13px; font-weight:400; color:#555; line-height:1.5; z-index:10; box-shadow:0 4px 16px rgba(0,0,0,0.10); white-space:normal; overflow-wrap:break-word; }
.apc-promo-tooltip.visible { display:block; }
.apc-promo-tooltip.apc-mort-tip { background:#fff; color:#333; border:1px solid #e0e0e0; border-radius:10px; padding:14px 16px; width:280px; box-shadow:0 4px 16px rgba(0,0,0,0.10); }
.apc-mort-tip-row { display:flex; justify-content:space-between; align-items:baseline; padding:5px 0; font-size:13px; font-weight:600; color:#333; }
.apc-mort-tip-row span:first-child { padding-right:16px; }
.apc-mort-tip-row span:last-child { white-space:nowrap; flex-shrink:0; }
.apc-mort-tip-second { color:#333; padding-bottom:10px; margin-bottom:4px; border-bottom:1px solid #f0f0f0; }
.apc-mort-tip-light { font-weight:400; color:#888; font-size:12px; padding:3px 0; }
.apc-finance-divider { height:15px; background:#f5f5f5; margin:0 -16px; }
.apc-finance-section { padding:16px 0 15px; }
.apc-finance-title { font-size:17px; font-weight:600; color:#1a1a1a; margin-bottom:12px; }
.apc-finance-item { display:grid; grid-template-columns:1fr 85px 110px; align-items:start; padding:10px 0; border-bottom:1px solid #f0f0f0; column-gap:12px; box-sizing:border-box; width:100%; }
.apc-inst-card { cursor:pointer; }
.apc-inst-card.apc-promo-hidden { display:none; }
.apc-inst-card.apc-promo-hidden.visible { display:block; }
.apc-inst-top { padding:10px 12px; background:#F2F2F7; border-radius:12px; transition:transform .3s cubic-bezier(.34,1.56,.64,1); transform-origin:center; }
.apc-inst-card.open .apc-inst-top { transform:scale(1.03); }
.apc-inst-head { display:flex; align-items:center; justify-content:space-between; }
.apc-inst-name { font-size:14px; font-weight:500; color:#1a1a1a; transition:transform .3s cubic-bezier(.34,1.56,.64,1); transform-origin:left center; display:inline-block; }
.apc-inst-card.open .apc-inst-name { transform:scale(1.08); }
.apc-inst-chevron { transition:transform 0.3s ease; flex-shrink:0; }
.apc-inst-card.open .apc-inst-chevron { transform:rotate(90deg); }
.apc-inst-tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
.apc-inst-tag { background:rgba(0,0,0,0.06); color:#555; font-size:11px; padding:3px 8px; border-radius:8px; white-space:nowrap; }
.apc-inst-tag.apc-inst-tag-pv { background:#34C759; color:#fff; }
.apc-mort-head-right { display:flex; align-items:center; gap:8px; flex-shrink:0; }
.apc-mort-rate { font-size:15px; font-weight:500; color:#1a1a1a; white-space:nowrap; }
.apc-mort-sub { font-size:12px; color:#8E8E93; margin-top:3px; }
.apc-inst-tag.apc-mort-tag-gov { background:#E1F5EE; color:#0F6E56; }
.apc-mtg-list { }
.apc-mtg-row { cursor:pointer; border-bottom:1px solid #E5E5EA; }
.apc-mtg-row:last-of-type { border-bottom:none; }
.apc-mtg-row.apc-promo-hidden { display:none; }
.apc-mtg-row.apc-promo-hidden.visible { display:block; }
.apc-mtg-head { display:flex; align-items:center; justify-content:space-between; padding:11px 0; gap:12px; }
.apc-mtg-info { min-width:0; }
.apc-mtg-name { font-size:14px; font-weight:500; color:#1a1a1a; transition:color .25s; }
.apc-mtg-sub { font-size:11px; color:#8E8E93; margin-top:2px; }
.apc-mtg-rate { display:flex; align-items:baseline; gap:1px; flex-shrink:0; }
.apc-mtg-rate-num { font-size:22px; font-weight:600; line-height:1; color:#1a1a1a; transition:transform .3s cubic-bezier(.34,1.56,.64,1); transform-origin:right center; }
.apc-mtg-rate-pct { font-size:13px; font-weight:600; color:#1a1a1a; }
.apc-mtg-low .apc-mtg-rate-num, .apc-mtg-low .apc-mtg-rate-pct { color:#0F6E56; }
.apc-mtg-row.open .apc-mtg-rate-num { transform:scale(1.18); }
.apc-mtg-row.open .apc-mtg-name { color:#0F6E56; }
.apc-mtg-panel { display:grid; grid-template-rows:0fr; transition:grid-template-rows .42s cubic-bezier(.4,0,.2,1); }
.apc-mtg-row.open .apc-mtg-panel { grid-template-rows:1fr; }
.apc-mtg-panel-inner { overflow:hidden; min-height:0; }
.apc-mtg-detail { padding:2px 0 14px; }
.apc-mtg-timeline { position:relative; padding-left:18px; margin-bottom:12px; }
.apc-mtg-timeline::before { content:''; position:absolute; left:4px; top:6px; bottom:6px; width:2px; background:linear-gradient(#34C759,#C7C7CC); }
.apc-mtg-tl-item { position:relative; padding:5px 0; opacity:0; transform:translateX(-6px); }
.apc-mtg-row.open .apc-mtg-tl-item { animation:apcStagger .4s forwards; }
.apc-mtg-row.open .apc-mtg-tl-item:nth-child(1){ animation-delay:.12s; }
.apc-mtg-row.open .apc-mtg-tl-item:nth-child(2){ animation-delay:.2s; }
.apc-mtg-tl-dot { position:absolute; left:-17px; top:9px; width:9px; height:9px; border-radius:50%; background:#fff; border:2px solid #34C759; }
.apc-mtg-tl-dot.gray { border-color:#C7C7CC; }
.apc-mtg-tl-period { font-size:11px; color:#8E8E93; }
.apc-mtg-tl-rate { font-size:14px; font-weight:600; color:#1a1a1a; }
.apc-mtg-note { font-size:13px; color:#555; margin-bottom:10px; opacity:0; transform:translateX(-6px); }
.apc-mtg-row.open .apc-mtg-note { animation:apcStagger .4s .14s forwards; }
.apc-mtg-chips { display:flex; flex-wrap:wrap; gap:6px; opacity:0; transform:translateY(4px); }
.apc-mtg-row.open .apc-mtg-chips { animation:apcStagger .4s .28s forwards; }
.apc-mtg-chip { font-size:11px; background:#fff; border:1px solid #E5E5EA; border-radius:8px; padding:4px 9px; color:#555; }
.apc-mtg-chip b { color:#1a1a1a; font-weight:500; }
.apc-mtg-deduction { margin-top:12px; padding:11px 12px; background:#E1F5EE; border-radius:10px; opacity:0; transform:translateY(4px); }
.apc-mtg-row.open .apc-mtg-deduction { animation:apcStagger .4s .34s forwards; }
.apc-mtg-ded-head { font-size:13px; color:#0F6E56; display:flex; align-items:center; gap:6px; }
.apc-mtg-ded-head b { font-weight:600; }
.apc-mtg-ded-ic { display:inline-block; font-size:13px; }
.apc-mtg-ded-rows { margin-top:7px; }
.apc-mtg-ded-row { display:flex; justify-content:space-between; font-size:12px; color:#0F6E56; padding:2px 0; }
.apc-mtg-ded-row span:last-child { font-weight:500; }
.apc-inst-drawer { display:grid; grid-template-rows:0fr; transition:grid-template-rows 0.42s cubic-bezier(.4,0,.2,1); }
.apc-inst-card.open .apc-inst-drawer { grid-template-rows:1fr; }
.apc-inst-drawer-inner { overflow:hidden; min-height:0; }
.apc-inst-body { margin-top:4px; padding:12px; background:#fff; border:1px solid #E5E5EA; border-radius:12px; }
.apc-inst-grid-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #F2F2F7; font-size:13px; }
.apc-inst-grid-row { opacity:0; transform:translateX(-6px); }
.apc-inst-body > * { opacity:0; transform:translateX(-6px); }
.apc-inst-card.open .apc-inst-body > * { animation:apcStagger 0.4s forwards; }
.apc-inst-card.open .apc-inst-body > *:nth-child(1){ animation-delay:.08s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(2){ animation-delay:.14s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(3){ animation-delay:.20s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(4){ animation-delay:.26s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(5){ animation-delay:.32s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(6){ animation-delay:.38s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(7){ animation-delay:.44s; }
.apc-inst-card.open .apc-inst-body > *:nth-child(8){ animation-delay:.50s; }
.apc-inst-grid-row:last-child { border-bottom:none; }
.apc-inst-grid-lbl { color:#8E8E93; }
.apc-inst-grid-val { font-weight:500; color:#1a1a1a; }
.apc-inst-sched-title { font-weight:600; color:#1a1a1a; font-size:13px; margin:10px 0 6px; }
.apc-inst-sched { display:flex; flex-direction:column; gap:4px; }
.apc-inst-sched-item { display:flex; gap:6px; font-size:13px; color:#555; line-height:1.5; }
.apc-inst-check { color:#34C759; flex-shrink:0; font-size:12px; margin-top:2px; }
.apc-inst-comment-title { font-weight:600; color:#1a1a1a; font-size:13px; margin:10px 0 6px; }
.apc-finance-item:last-child { border-bottom:none; }
.apc-finance-name { font-size:14px; color:#555; font-weight:400; min-width:0; padding-top:14px; line-height:1.6; }
.apc-finance-cols { display:contents; }
.apc-finance-col { text-align:right; display:flex; flex-direction:column; align-items:flex-end; }
.apc-finance-col-label { font-size:11px; color:#bbb; display:block; text-align:right; }
.apc-finance-col-value { font-size:14px; color:#555; font-weight:400; white-space:normal; word-break:break-word; display:block; text-align:right; line-height:1.6; }
.apc-finance-detail { font-size:14px; color:#1a1a1a; font-weight:400; text-align:right; }
.apc-finance-rate { font-size:14px; color:#1a1a1a; font-weight:400; text-align:right; white-space:nowrap; }
.apc-finance-disclaimer { font-size:11px; color:#bbb; line-height:1.4; margin-top:12px; margin-bottom:15px; padding-top:10px; border-top:1px solid #f0f0f0; }
.apc-fin-wrap { position:relative; }
.apc-fin-fade { position:absolute; bottom:0; left:0; right:0; height:40px; background:linear-gradient(transparent, #fff); pointer-events:none; transition:opacity 0.3s; }
.apc-fin-fade.hidden { opacity:0; }
.apc-fin-more { font-size:13px; color:#c8a96e; cursor:pointer; margin-top:4px; padding-bottom:15px; display:inline-block; }
.apc-hoff-pill { display:inline-flex; align-items:center; gap:4px; background:#E11D2C; padding:3px 8px; border-radius:8px; font-size:12px; line-height:1.4; cursor:pointer; position:relative; }
.apc-hoff-pill .apc-hoff-logo { height:17px; width:auto; display:block; fill:#fff; }
.apc-onreq-badge { display:inline-flex; align-items:center; gap:5px; background:#f5f0eb; color:#8a6a3a; font-size:13px; font-weight:500; padding:4px 10px; border-radius:20px; cursor:pointer; user-select:none; position:relative; }
.apc-onreq-badge svg { width:14px; height:14px; flex-shrink:0; }
.apc-onreq-tooltip { display:none; position:absolute; top:calc(100% + 8px); right:0; width:280px; background:#1a1a1a; color:#fff; font-size:12px; line-height:1.5; padding:10px 12px; border-radius:10px; z-index:20; box-shadow:0 4px 16px rgba(0,0,0,0.2); white-space:normal; overflow-wrap:break-word; }
.apc-onreq-tooltip::before { content:''; position:absolute; top:-5px; right:14px; width:10px; height:10px; background:#1a1a1a; transform:rotate(45deg); border-radius:2px; }
.apc-onreq-badge.open .apc-onreq-tooltip { display:block; }
.apt-price.onreq { color:#8a6a3a; }
.apc-booked-badge { display:inline-flex; align-items:center; gap:5px; background:#f0f4ff; color:#4a6fa5; font-size:13px; font-weight:500; padding:4px 10px; border-radius:20px; cursor:pointer; user-select:none; position:relative; }
.apc-booked-badge svg { width:14px; height:14px; flex-shrink:0; }
.apc-booked-tooltip { display:none; position:absolute; top:calc(100% + 8px); left:0; right:auto; width:280px; background:#1a1a1a; color:#fff; font-size:12px; line-height:1.6; padding:10px 12px; border-radius:10px; z-index:20; box-shadow:0 4px 16px rgba(0,0,0,0.2); white-space:normal; overflow-wrap:break-word; }
.apc-booked-tooltip::before { content:''; position:absolute; top:-5px; left:14px; width:10px; height:10px; background:#1a1a1a; transform:rotate(45deg); border-radius:2px; }
.apc-booked-badge.open .apc-booked-tooltip { display:block; }
.apc-booked-pill { display:inline-flex; align-items:center; gap:4px; background:#4a6fa5; color:#fff; font-size:12px; font-weight:500; padding:3px 8px; border-radius:8px; white-space:nowrap; letter-spacing:0.1px; line-height:1.4; cursor:pointer; position:relative; }
.apt-booked-label { display:inline-flex; align-items:center; background:#f0f4ff; color:#4a6fa5; font-size:11px; font-weight:600; padding:0 6px; height:16px; border-radius:3px; margin-left:6px; vertical-align:middle; white-space:nowrap; }
.apt-booked-label svg { display:none; }
.apc-consult-btn { width:100%; padding:14px; background:#00a73e; color:#fff; border:none; border-radius:12px; font-size:15px; font-weight:500; font-family:'Inter Tight',sans-serif; cursor:pointer; letter-spacing:0.02em; transition:opacity 0.2s; display:flex; align-items:center; justify-content:center; gap:0; overflow:hidden; position:relative; }
.apc-consult-btn:active { opacity:0.85; }

.apc-consult-btn-text { transition:transform 0.5s cubic-bezier(0.34,1.56,0.64,1); }
.apc-similar-title { font-size:17px; font-weight:600; color:#1a1a1a; padding:16px 0 10px; }
.apc-similar-scroll { display:flex; gap:10px; overflow-x:auto; margin:0 -16px; padding:0 16px 15px; scrollbar-width:none; -webkit-overflow-scrolling:touch; }
.apc-similar-scroll::-webkit-scrollbar { display:none; }
.apc-similar-card { flex:0 0 148px; cursor:pointer; -webkit-tap-highlight-color:transparent; }
.apc-similar-card:active { opacity:0.8; }
.apc-similar-img { width:148px; height:148px; background:#f5f5f5; border-radius:12px; overflow:hidden; border:1px solid #ebebeb; display:flex; align-items:center; justify-content:center; margin-bottom:8px; position:relative; }
.apc-similar-img img { width:100%; height:100%; object-fit:contain; mix-blend-mode:multiply; padding:8px; box-sizing:border-box; }
.apc-similar-badge { display:inline-block; background:#e8244b; color:#fff; font-size:10px; font-weight:700; padding:2px 6px; border-radius:6px; margin-left:6px; vertical-align:middle; flex-shrink:0; }
.apc-similar-price { font-size:14px; font-weight:600; color:#1a1a1a; margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.apc-similar-meta { font-size:12px; color:#888; font-weight:300; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* == Renovation spoiler ============================================ */
.apc-renovation-spoiler { }
.apc-ren-head { display:flex; align-items:flex-start; justify-content:space-between; padding:16px 0 14px; cursor:pointer; user-select:none; gap:12px; }
.apc-ren-title-wrap { display:flex; flex-direction:column; gap:3px; }
.apc-ren-eyebrow { font-size:11px; font-weight:400; letter-spacing:0.04em; text-transform:uppercase; color:#c8a96e; margin-bottom:2px; }
.apc-ren-title-q { font-size:17px; font-weight:600; color:#1a1a1a; line-height:1.3; }
.apc-ren-title-s { font-size:13px; font-weight:400; color:#888; line-height:1.4; margin-top:3px; }
.apc-ren-title-s b { font-weight:600; color:#1a1a1a; }
.apc-ren-chev {
  flex-shrink:0;
  margin-top:3px;
  width:18px;
  height:18px;
  background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%230F1014" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>');
  background-size:contain;
  background-repeat:no-repeat;
  background-position:center;
  transition:transform 0.22s ease;
}
.apc-ren-chev svg { display:none; }
.apc-ren-open .apc-ren-chev { transform:rotate(90deg); }
.apc-ren-body-wrap { position:relative; max-height:100px; overflow:hidden; transition:max-height 0.5s ease; }
.apc-ren-open .apc-ren-body-wrap { max-height:2000px; }
.apc-ren-body { padding:0 0 20px; }
.apc-ren-fade { position:absolute; bottom:0; left:0; right:0; height:80px; background:linear-gradient(to bottom,transparent,#fff); pointer-events:none; transition:opacity 0.4s; z-index:1; }
.apc-ren-open .apc-ren-fade { opacity:0; }
.apc-ren-free-banner { display:flex; align-items:flex-start; gap:10px; background:#EAF3DE; border-radius:10px; padding:12px 13px; margin:14px 0 2px; }
.apc-ren-free-text { font-size:12px; color:#3B6D11; line-height:1.5; }
.apc-ren-free-text b { font-weight:500; color:#0F6E56; }
.apc-ren-phase-row { display:flex; align-items:center; gap:8px; margin:18px 0 14px; }
.apc-ren-phase-line { flex:1; height:0.5px; background:rgba(0,0,0,0.10); }
.apc-ren-pill { font-size:10px; font-weight:500; padding:3px 10px; border-radius:20px; white-space:nowrap; }
.apc-ren-pill--blue { background:#E6F1FB; color:#185FA5; }
.apc-ren-pill--amber { background:#FAEEDA; color:#854F0B; }
.apc-ren-pill--green { background:#EAF3DE; color:#3B6D11; }
.apc-ren-timeline { position:relative; padding-left:34px; }
.apc-ren-step { position:relative; padding-bottom:18px; }
.apc-ren-step--last { padding-bottom:0; }
.apc-ren-step-line { position:absolute; left:-22px; top:20px; bottom:0; width:1px; background:rgba(0,0,0,0.10); }
.apc-ren-dot { position:absolute; left:-29px; top:3px; width:14px; height:14px; border-radius:50%; border:1.5px solid; display:flex; align-items:center; justify-content:center; font-size:8px; font-weight:600; background:#fff; z-index:1; }
.apc-ren-dot--blue { border-color:#378ADD; color:#185FA5; }
.apc-ren-dot--amber { border-color:#EF9F27; color:#854F0B; }
.apc-ren-dot--green { border-color:#1D9E75; color:#0F6E56; }
.apc-ren-step-title { font-size:12.5px; font-weight:500; color:#1a1a1a; margin-bottom:2px; line-height:1.35; }
.apc-ren-step-desc { font-size:11.5px; color:#666; line-height:1.45; }
.apc-ren-finish { position:relative; height:220px; border-radius:12px; overflow:hidden; margin-top:20px; }
.apc-ren-finish-photo { width:100%; height:100%; object-fit:cover; object-position:center; display:block; }
.apc-ren-finish-overlay { position:absolute; inset:0; background:linear-gradient(to top,rgba(8,8,6,0.82) 0%,rgba(8,8,6,0.25) 55%,rgba(8,8,6,0.00) 100%); }
.apc-ren-finish-text { position:absolute; bottom:0; left:0; right:0; padding:18px 18px 20px; }
.apc-ren-finish-tag { font-size:10px; font-weight:500; letter-spacing:0.07em; color:rgba(255,255,255,0.50); text-transform:uppercase; margin-bottom:6px; }
.apc-ren-finish-title { font-size:17px; font-weight:500; color:#fff; line-height:1.3; margin-bottom:4px; }
.apc-ren-finish-sub { font-size:12px; color:rgba(255,255,255,0.58); line-height:1.4; }
.apc-ren-cta { width:100%; padding:10px 0; margin-top:16px; border-radius:9px; border:0.5px solid #1D9E75; background:transparent; color:#0F6E56; font-size:13px; font-weight:500; cursor:pointer; transition:background 0.15s; font-family:inherit; }
.apc-ren-cta:hover { background:#EAF3DE; }
.apc-ren-free-banner--alert { background:#fdf0f0; }
.apc-ren-free-text--alert { color:#8a1a1a; }
.apc-ren-free-text--alert b { color:#c0182e; }
.apc-ren-subtitle { font-size:13px; color:#555; line-height:1.5; margin:14px 0 2px; }
.apc-ren-brand { font-weight:500; color:#1a1a1a; }
/* == end Renovation spoiler ======================================== */

/* ════════════════ ROYALTY OVERRIDES (sprint-1) ════════════════ */
/* — все правки попапа карточки квартиры, сделанные в дизайн-сессии — */

/* Высота контейнера планировки + симметричный воздух */
#apc-plan-area { height:400px !important; max-height:400px !important; min-height:400px !important; aspect-ratio:auto !important; padding-top:6px; padding-bottom:8px; box-sizing:border-box; }

/* Точки скрыты — миниатюр снизу достаточно */
#apc-inline-dots { display:none !important; }

/* Толстые декоративные разделители больше не нужны при островной верстке */
.apc-finance-divider { display:none !important; }

/* Тонкие линии-разделители строк паспорта */
.apc-row { border-bottom:none !important; }

/* === Островная вёрстка === */
.apc-body { background:#F2F2F7 !important; padding:0 0 12px !important; }

[data-island="1"] {
  background:#fff;
  border-radius:14px;
  padding:16px;
  margin-bottom:4px;
}

#apc-top-island {
  background:#fff;
  border-radius:0 0 14px 14px;
  margin:0 0 4px;
  padding:0;
  overflow:visible;
  position:relative;
  z-index:2;
  min-height:577px;
  flex-shrink:0;
}
#apc-top-island > #apc-plan-area { aspect-ratio:auto; overflow:hidden; }

/* === Цена === */
.apc-price-row {
  display:flex !important;
  flex-direction:column !important;
  gap:0 !important;
  padding:14px 16px 18px !important;
  margin:0 !important;
  border-bottom:none !important;
  background:transparent !important;
}
#apc-price-line {
  display:flex;
  align-items:center;
  gap:8px;
  flex-wrap:wrap;
}
#apc-badges-line {
  display:flex;
  align-items:center;
  gap:8px;
  margin-top:6px;
}
#apc-price-main, .apc-price-main-styled {
  font-size:20px !important;
  font-weight:600 !important;
  letter-spacing:-0.3px !important;
  line-height:24px !important;
  color:#0F1014 !important;
  display:inline-block !important;
  width:auto !important;
  margin:0 !important;
}
#apc-old-price-wrap { display:flex; align-items:center; gap:8px; }
.apc-old-price-styled {
  font-size:13px !important;
  font-weight:400 !important;
  color:#8E8E93 !important;
  text-decoration:line-through !important;
}
#apc-badge-inline {
  display:inline-flex;
  align-items:center;
  padding:3px 8px;
  background:#E11D2C;
  color:#fff;
  font-size:12px;
  font-weight:500;
  border-radius:8px;
  line-height:1.4;
  letter-spacing:0.1px;
}

/* === Подзаголовок === */
#apc-subtitle {
  font-size:14px;
  font-weight:400;
  color:#3C3C43;
  line-height:1.4;
  margin-top:4px;
  display:flex;
  align-items:center;
  flex-wrap:wrap;
  gap:4px 6px;
  width:100%;
  letter-spacing:0;
}

/* === Сетка характеристик — одна строка === */
#apc-spec-grid {
  display:flex;
  gap:0;
  margin:0;
  width:100%;
}
.apc-spec-cell { min-width:0; flex:1 1 0; text-align:center; position:relative; }
.apc-spec-cell:not(:last-child)::after {
  content:'';
  position:absolute;
  right:0;
  top:4px;
  bottom:4px;
  width:1px;
  background:#E5E5EA;
}
.apc-spec-inner { display:inline-block; text-align:center; }
.apc-spec-value {
  font-size:14px;
  font-weight:500;
  color:#0F1014;
  line-height:1.2;
  letter-spacing:-0.1px;
  white-space:nowrap;
}
.apc-spec-label {
  font-size:11px;
  color:#8E8E93;
  line-height:1.3;
  margin-top:3px;
  letter-spacing:0.1px;
}
.apc-spec-icon {
  display:flex;
  justify-content:center;
  margin-bottom:4px;
}
.apc-spec-icon img {
  width:20px;
  height:20px;
  opacity:0.45;
}

/* === Пилюля «Вид на X» === */
#apc-view-banner {
  display:inline-flex;
  align-items:center;
  gap:5px;
  padding:3px 8px;
  background:#E8F5E9;
  color:#1B5E20;
  border-radius:8px;
  font-size:12px;
  font-weight:500;
  letter-spacing:0.1px;
  line-height:1.4;
  white-space:nowrap;
  cursor:pointer;
  position:relative;
  flex-shrink:0;
}

/* === Карточки преимуществ ЖК — серый фон #F2F2F7, без двойной подложки === */
.apc-feature-card {
  background:#F2F2F7 !important;
  border:none !important;
  border-radius:10px !important;
  padding:0 !important;
  overflow:hidden !important;
}
.apc-feature-card img {
  border-radius:0 !important;
  margin-bottom:8px !important;
  display:block;
  width:100%;
}
.apc-feature-card-text {
  padding:0 10px 10px !important;
  margin:0 !important;
  font-size:13px !important;
  line-height:1.3 !important;
  color:#0F1014 !important;
  font-weight:400 !important;
  display:block !important;
  -webkit-line-clamp:unset !important;
  -webkit-box-orient:unset !important;
  overflow:visible !important;
}
.apc-features-scroll { align-items:stretch !important; }

/* === Унификация текстовых ссылок (бывших золотых) === */
#apc-about-more,
.apc-fin-more {
  color:#0F1014 !important;
  font-size:14px !important;
  font-weight:500 !important;
  cursor:pointer;
  display:inline-flex !important;
  align-items:center;
  gap:4px;
  margin-top:12px;
  margin-bottom:0;
}
#apc-about-more::after,
.apc-fin-more::after {
  content:'';
  width:18px;
  height:18px;
  background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%230F1014" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>');
  background-size:contain;
  background-repeat:no-repeat;
  display:inline-block;
  margin-left:4px;
  transition:transform 0.18s ease;
}
#apc-about-more[data-expanded]::after,
.apc-fin-more[data-expanded]::after {
  transform:rotate(180deg);
}

/* === Шевроны рассрочек — SVG жирный, поворот при .open === */
.apc-inst-chevron {
  font-size:0 !important;
  width:18px;
  height:18px;
  display:inline-block;
  background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%230F1014" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>');
  background-size:contain;
  background-repeat:no-repeat;
  background-position:center;
  transition:transform 0.18s ease;
  flex-shrink:0;
  padding-top:0 !important;
  color:transparent !important;
}

/* === Финансовый disclaimer — на сером, между островами === */
.apc-finance-disclaimer {
  padding:12px 16px 4px !important;
  font-size:12px !important;
  color:#8E8E93 !important;
  background:transparent !important;
  margin:0 !important;
  border:none !important;
}

/* === Sticky header при скролле === */
.apc-header { transition:background 0.18s ease, border-color 0.18s ease, backdrop-filter 0.18s ease !important; }
.apc-header.scrolled {
  background:rgba(255,255,255,0.92) !important;
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
  border-bottom:1px solid #E5E5EA;
}
.apc-header-center {
  position:absolute;
  left:50%;
  top:50%;
  transform:translate(-50%, -50%);
  text-align:center;
  pointer-events:none;
  opacity:0;
  transition:opacity 0.18s ease;
  max-width:60%;
  white-space:nowrap;
  overflow:hidden;
}
.apc-header.scrolled .apc-header-center { opacity:1; }
.apc-header-center .hdr-price { font-size:15px; font-weight:600; color:#0F1014; line-height:1.1; }
.apc-header-center .hdr-sub { font-size:11px; color:#8E8E93; line-height:1.2; margin-top:1px; overflow:hidden; text-overflow:ellipsis; }

/* ════════════════ END ROYALTY OVERRIDES ════════════════ */

"""
    js = r"""function _dp(n,w1,w2,w5){n=Math.abs(n)%100;var n1=n%10;if(n>10&&n<20)return w5;if(n1>1&&n1<5)return w2;if(n1===1)return w1;return w5;}
function _onReqTip(el){el.classList.toggle('open');document.addEventListener('click',function h(e){if(!el.contains(e.target)){el.classList.remove('open');document.removeEventListener('click',h);}},{once:false});}
function _bookedTip(el,e){
  if(e){e.stopPropagation();}
  var tip=el.querySelector('.apc-promo-tooltip');
  if(!tip)return;
  var isOpen=tip.classList.contains('visible');
  document.querySelectorAll('.apc-promo-tooltip.visible').forEach(function(t){t.classList.remove('visible');});
  if(!isOpen){
    tip.style.left='50%';tip.style.right='auto';tip.style.transform='translateX(-50%)';
    tip.classList.add('visible');
    var r=tip.getBoundingClientRect();var pad=8;
    if(r.right>window.innerWidth-pad){tip.style.left='auto';tip.style.right='0';tip.style.transform='none';}
    else if(r.left<pad){tip.style.left='0';tip.style.right='auto';tip.style.transform='none';}
  }
  document.addEventListener('click',function h(ev){if(!el.contains(ev.target)){tip.classList.remove('visible');document.removeEventListener('click',h);}},{once:false});
}
function _viewTip(el,e){
  if(e){e.stopPropagation();}
  var tip=el.querySelector('.apc-promo-tooltip');
  if(!tip)return;
  var isOpen=tip.classList.contains('visible');
  document.querySelectorAll('.apc-promo-tooltip.visible').forEach(function(t){t.classList.remove('visible');});
  if(!isOpen){
    tip.style.left='50%';tip.style.right='auto';tip.style.transform='translateX(-50%)';
    tip.classList.add('visible');
    var r=tip.getBoundingClientRect();var pad=8;
    if(r.right>window.innerWidth-pad){tip.style.left='auto';tip.style.right='0';tip.style.transform='none';}
    else if(r.left<pad){tip.style.left='0';tip.style.right='auto';tip.style.transform='none';}
  }
  document.addEventListener('click',function h(ev){if(!el.contains(ev.target)){tip.classList.remove('visible');document.removeEventListener('click',h);}},{once:false});
}
function _togInst(cardId){var card=document.getElementById(cardId);if(!card)return;var was=card.classList.contains('open');document.querySelectorAll('.apc-inst-card.open').forEach(function(c){c.classList.remove('open')});if(!was)card.classList.add('open');}
function _togInstMore(el){var exp=el.classList.toggle('expanded');var cards=el.parentNode.querySelectorAll('.apc-inst-card.apc-promo-hidden');cards.forEach(function(c){exp?c.classList.add('visible'):c.classList.remove('visible')});var total=cards.length;var w=total===1?'программа':(total<5?'программы':'программ');el.textContent=exp?'Свернуть':'Ещё '+total+' '+w;}
function _togMort(cardId){var card=document.getElementById(cardId);if(!card)return;var was=card.classList.contains('open');document.querySelectorAll('#apc-mort-block .apc-inst-card.open').forEach(function(c){c.classList.remove('open')});if(!was)card.classList.add('open');}
function _togMortMore(el){var exp=el.classList.toggle('expanded');var cards=el.parentNode.querySelectorAll('.apc-inst-card.apc-promo-hidden');cards.forEach(function(c){exp?c.classList.add('visible'):c.classList.remove('visible')});var total=cards.length;var w=total===1?'программа':(total<5?'программы':'программ');el.textContent=exp?'Свернуть':'Ещё '+total+' '+w;}
function _togMtg(rowId){var row=document.getElementById(rowId);if(!row)return;var was=row.classList.contains('open');document.querySelectorAll('#apc-mort-block .apc-mtg-row.open').forEach(function(c){c.classList.remove('open')});if(!was)row.classList.add('open');}
function _togMtgMore(el){var exp=el.classList.toggle('expanded');var rows=el.parentNode.querySelectorAll('.apc-mtg-row.apc-promo-hidden');rows.forEach(function(c){exp?c.classList.add('visible'):c.classList.remove('visible')});var total=rows.length;var w=total===1?'программа':(total<5?'программы':'программ');el.textContent=exp?'Свернуть':'Ещё '+total+' '+w;}
      function _togFin(btn,wrapId,fadeId){var w=document.getElementById(wrapId);if(!w)return;w.querySelectorAll('.apc-promo-hidden').forEach(function(el){el.classList.toggle('visible')});var f=document.getElementById(fadeId);if(f)f.classList.toggle('hidden');btn.textContent=btn.textContent==='Свернуть'?btn.dataset.more:'Свернуть';}
function _promoTip(btn){var tip=btn.nextElementSibling;if(!tip||!tip.classList.contains('apc-promo-tooltip')){tip=btn.closest('[style*="position"]').querySelector('.apc-promo-tooltip')||btn.parentElement.parentElement.querySelector('.apc-promo-tooltip');}if(!tip)return;var isOpen=tip.classList.contains('visible');document.querySelectorAll('.apc-promo-tooltip.visible').forEach(function(t){t.classList.remove('visible')});document.querySelectorAll('.apc-promo-info.active').forEach(function(b){b.classList.remove('active')});if(!isOpen){tip.style.left='50%';tip.style.right='auto';tip.style.transform='translateX(-50%)';tip.classList.add('visible');btn.classList.add('active');var r=tip.getBoundingClientRect();var pad=8;if(r.right>window.innerWidth-pad){tip.style.left='auto';tip.style.right='0';tip.style.transform='none';}else if(r.left<pad){tip.style.left='0';tip.style.right='auto';tip.style.transform='none';}}}
document.addEventListener('click',function(e){if(!e.target.classList.contains('apc-promo-info')){document.querySelectorAll('.apc-promo-tooltip.visible').forEach(function(t){t.classList.remove('visible')});document.querySelectorAll('.apc-promo-info.active').forEach(function(b){b.classList.remove('active')});}if(!e.target.closest('.apc-promo-card')){document.querySelectorAll('.apc-promo-card.open').forEach(function(c){c.classList.remove('open')});}});
function _togPromoCard(el){var was=el.classList.contains('open');document.querySelectorAll('.apc-promo-card.open').forEach(function(c){c.classList.remove('open')});if(!was)el.classList.add('open');}
function _togPromoMore(el){var exp=el.classList.toggle('expanded');var cards=el.parentNode.querySelectorAll('.apc-promo-extra');cards.forEach(function(c){exp?c.classList.add('visible'):c.classList.remove('visible')});var total=cards.length;var w=total===1?'акция':(total<5?'акции':'акций');el.textContent=exp?'Свернуть':'Ещё '+total+' '+w;}
const mOverlay  = document.getElementById('mobile-filter-overlay');
const mPopup    = document.getElementById('mobile-filter-popup');
const mFloatBtn = document.getElementById('floating-filter-btn');
const mApplyBtn = document.getElementById('m-apply-btn');
const mFloatTxt = mFloatBtn.querySelector('span');
function toggleMobileFilter(show) {
if (show) { mOverlay.classList.add('active'); mPopup.classList.add('active'); document.body.style.overflow = 'hidden';
  requestAnimationFrame(function(){ requestAnimationFrame(function(){
    ['m-slider-area','m-slider-price'].forEach(function(k){
      if (SL[k] && SL[k].noUiSlider) smartRepel(SL[k].noUiSlider);
    });
  }); });
}
else { mOverlay.classList.remove('active'); mPopup.classList.remove('active'); document.body.style.overflow = ''; }
}
function toggleDesktopFilterModal(show) {
const o = document.getElementById('desktop-filter-modal-overlay');
if (show) { o.classList.add('active'); document.body.style.overflow = 'hidden'; }
else       { o.classList.remove('active'); document.body.style.overflow = ''; }
}
mFloatBtn.addEventListener('click', () => { window.innerWidth > 900 ? toggleDesktopFilterModal(true) : toggleMobileFilter(true); });
mOverlay.addEventListener('click',  () => toggleMobileFilter(false));
mApplyBtn.addEventListener('click', () => {
toggleMobileFilter(false);
setTimeout(() => { const c = document.querySelector('.apt-card[style*="display: flex"]'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
});
const dModalApplyBtn = document.getElementById('desktop-modal-apply-btn');
dModalApplyBtn.addEventListener('click', () => {
toggleDesktopFilterModal(false);
setTimeout(() => { const c = document.querySelector('.apt-card[style*="display: flex"]'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
});
document.getElementById('desktop-filter-modal-overlay').addEventListener('click', e => { if (e.target.id === 'desktop-filter-modal-overlay') toggleDesktopFilterModal(false); });
const dragHandle = document.querySelector('.m-header');
let startY = 0, isDragging = false;
dragHandle.addEventListener('pointerdown', e => { if (e.button !== 0) return; isDragging = true; startY = e.clientY; dragHandle.setPointerCapture(e.pointerId); mPopup.style.transition = 'none'; });
dragHandle.addEventListener('pointermove', e => { if (!isDragging) return; const d = e.clientY - startY; if (d > 0) mPopup.style.transform = `translate3d(0,${d}px,0)`; });
dragHandle.addEventListener('pointerup',   e => {
if (!isDragging) return; isDragging = false; dragHandle.releasePointerCapture(e.pointerId);
const d = e.clientY - startY;
if (d > 120) { mPopup.style.transition = 'transform 0.4s cubic-bezier(0.25,1,0.5,1)'; mPopup.style.transform = 'translate3d(0,110%,0)'; setTimeout(() => { toggleMobileFilter(false); mPopup.style.transform = ''; mPopup.style.transition = ''; }, 400); }
else          { mPopup.style.transition = 'transform 0.3s cubic-bezier(0.4,0,0.2,1)'; mPopup.style.transform = ''; setTimeout(() => { mPopup.style.transition = ''; }, 300); }
});
let selectedMapDistricts = [];
let _mapLoaded = false;
function loadMapSVG() {
if (_mapLoaded) return; _mapLoaded = true;
// Карта из GeoJSON — без внешнего fetch
var tgt = document.getElementById("map-svg");
[
  'M 4.9,41.5 L 47.2,104.9 L 65.7,182.6 L 65.6,319.5 L 98.9,414.0 L 137.0,428.8 L 149.4,411.4 L 170.3,411.4 L 187.2,417.0 L 204.0,422.5 L 218.0,425.7 L 225.7,428.4 L 234.9,433.8 L 237.5,436.9 L 245.4,447.4 L 253.9,460.8 L 261.6,469.1 L 267.7,472.9 L 274.5,475.0 L 292.0,477.1 L 298.2,484.9 L 365.4,509.8 L 389.6,530.8 L 419.0,532.9 L 452.5,537.9 L 475.9,527.7 L 504.2,508.1 L 502.5,505.1 L 503.8,500.3 L 508.1,501.9 L 522.2,492.1 L 535.5,454.3 L 549.7,458.3 L 561.6,455.4 L 562.4,450.2 L 523.7,436.1 L 505.9,412.5 L 513.6,383.8 L 531.4,375.0 L 536.9,375.5 L 533.0,365.6 L 534.0,357.8 L 529.7,354.0 L 516.7,349.9 L 501.9,346.2 L 424.9,328.7 L 388.0,335.0 L 351.2,305.2 L 342.1,258.4 L 341.2,243.5 L 333.1,215.4 L 306.5,153.5 L 324.6,147.1 L 323.0,88.1 L 286.2,55.2 L 268.9,57.4 L 191.6,24.9 L 86.4,1.4 L 4.9,41.5 Z',
  'M 533.0,365.6 L 536.9,375.5 L 537.9,375.6 L 552.7,382.7 L 563.9,388.1 L 570.8,391.4 L 584.3,402.2 L 587.0,404.0 L 590.4,405.7 L 592.6,406.9 L 596.8,407.8 L 603.2,409.3 L 604.2,411.0 L 608.8,405.0 L 603.4,404.0 L 592.5,403.1 L 574.1,388.6 L 556.6,379.8 L 544.1,372.9 L 537.0,368.9 L 535.2,367.9 L 533.0,365.6 Z',
  'M 529.9,354.0 L 533.9,357.7 L 540.0,354.6 L 547.2,352.9 L 555.7,350.2 L 566.8,348.8 L 581.6,349.9 L 585.5,348.3 L 594.8,347.3 L 608.8,352.4 L 617.1,359.5 L 621.6,371.4 L 622.5,377.2 L 623.8,385.1 L 625.0,393.5 L 631.6,400.4 L 640.0,400.2 L 646.0,400.0 L 648.3,398.6 L 653.1,395.6 L 655.7,393.4 L 658.7,390.4 L 663.2,390.3 L 665.2,392.1 L 669.4,397.4 L 668.9,403.8 L 668.2,411.5 L 665.3,422.3 L 663.2,429.9 L 661.6,436.0 L 667.2,450.0 L 669.3,451.7 L 678.1,466.0 L 680.2,467.6 L 683.7,470.3 L 687.0,472.9 L 689.9,476.4 L 693.2,480.4 L 695.5,485.0 L 697.3,489.5 L 698.9,494.3 L 700.0,500.5 L 701.3,510.1 L 702.0,511.7 L 707.9,525.1 L 710.4,530.3 L 715.8,534.4 L 721.9,535.2 L 726.2,537.9 L 727.8,540.1 L 734.4,551.4 L 734.7,555.0 L 733.9,558.3 L 732.2,563.0 L 732.6,566.1 L 732.7,570.9 L 735.1,575.2 L 744.2,577.1 L 746.4,578.4 L 748.4,579.6 L 749.8,581.0 L 752.4,584.1 L 755.2,587.3 L 760.2,592.1 L 765.4,594.8 L 767.3,594.5 L 770.4,594.3 L 772.9,593.4 L 775.5,592.4 L 777.5,590.6 L 780.5,588.9 L 782.8,590.0 L 783.2,592.6 L 782.9,597.5 L 783.3,604.8 L 787.1,609.0 L 789.9,611.5 L 795.3,614.9 L 801.0,620.2 L 806.1,625.5 L 809.3,632.6 L 812.2,637.7 L 817.6,641.3 L 821.5,646.3 L 824.4,650.7 L 827.6,655.8 L 833.3,661.2 L 836.9,662.9 L 841.5,664.4 L 846.5,664.8 L 851.8,665.2 L 856.9,668.0 L 861.5,671.6 L 867.6,674.8 L 872.8,675.7 L 877.6,679.7 L 882.5,682.4 L 889.8,682.6 L 894.9,681.9 L 902.2,682.8 L 908.6,684.3 L 911.4,686.7 L 914.6,691.6 L 915.9,697.6 L 918.2,705.7 L 922.8,709.7 L 927.2,709.0 L 932.6,707.2 L 936.6,703.3 L 937.5,698.5 L 943.0,698.0 L 947.6,695.2 L 950.5,688.4 L 951.6,679.2 L 954.4,672.3 L 957.3,663.8 L 960.7,658.0 L 963.6,652.2 L 970.0,648.6 L 972.4,647.8 L 977.0,647.1 L 979.4,643.3 L 983.4,636.9 L 985.9,633.0 L 991.0,630.0 L 999.6,628.2 L 1005.6,625.1 L 1009.3,626.7 L 1016.9,629.6 L 1022.5,628.5 L 1029.3,626.7 L 1036.2,621.6 L 1029.2,615.3 L 1016.6,618.1 L 1009.9,618.2 L 1001.2,622.3 L 990.6,624.9 L 983.6,629.8 L 976.6,638.4 L 971.5,638.4 L 963.6,641.4 L 961.5,647.3 L 957.6,651.0 L 954.7,658.6 L 950.4,667.2 L 948.1,676.6 L 947.3,687.2 L 943.6,690.8 L 933.2,691.8 L 928.0,694.3 L 921.7,692.6 L 920.8,688.4 L 918.2,682.9 L 913.4,678.0 L 907.3,673.7 L 900.2,671.9 L 891.0,673.5 L 883.4,673.5 L 879.4,671.2 L 874.0,669.1 L 865.5,668.1 L 860.5,664.8 L 854.2,660.8 L 847.2,659.2 L 838.8,656.0 L 833.5,651.8 L 827.9,644.0 L 821.4,635.2 L 811.3,622.8 L 808.7,617.6 L 802.0,613.5 L 794.6,607.8 L 789.1,605.2 L 787.2,601.5 L 788.0,596.9 L 789.0,593.0 L 788.1,588.7 L 786.8,585.7 L 782.6,583.6 L 779.0,584.4 L 769.0,589.6 L 759.2,584.0 L 751.5,575.9 L 742.5,569.8 L 738.5,566.3 L 738.2,557.8 L 739.6,556.3 L 739.2,550.4 L 735.1,541.8 L 732.7,539.9 L 728.4,533.1 L 725.3,531.5 L 719.3,530.4 L 712.8,527.0 L 710.1,520.9 L 705.0,508.5 L 702.0,490.0 L 699.9,484.6 L 695.3,476.8 L 688.9,468.4 L 681.9,461.6 L 677.7,452.9 L 669.3,438.4 L 668.5,432.5 L 672.5,412.7 L 674.1,396.9 L 672.4,390.0 L 670.8,388.4 L 665.5,385.3 L 657.7,385.6 L 651.5,392.5 L 642.9,396.2 L 633.7,395.0 L 633.5,394.2 L 632.2,394.4 L 628.4,392.7 L 625.3,382.6 L 624.4,370.8 L 619.4,357.7 L 614.7,353.0 L 613.6,353.4 L 609.5,349.7 L 595.3,345.1 L 590.6,344.5 L 585.5,345.8 L 580.4,347.7 L 577.0,347.9 L 573.8,346.7 L 568.2,346.1 L 565.8,346.3 L 553.5,347.5 L 552.4,347.9 L 549.2,349.1 L 546.1,349.9 L 544.3,348.8 L 542.7,348.3 L 538.3,350.0 L 529.9,354.0 Z',
  'M 562.4,450.0 L 561.6,455.2 L 569.5,455.4 L 570.2,456.6 L 570.4,461.9 L 571.5,457.1 L 576.0,450.1 L 580.3,433.8 L 591.6,427.8 L 604.5,416.2 L 605.5,415.9 L 615.2,408.5 L 631.3,400.5 L 631.6,400.4 L 625.1,393.5 L 608.9,405.0 L 604.3,411.0 L 598.1,417.4 L 590.1,421.8 L 584.2,425.2 L 580.7,427.2 L 576.8,432.0 L 572.3,449.4 L 568.3,451.5 L 562.4,450.0 Z'
].forEach(function(dd){
  var wp=document.createElementNS("http://www.w3.org/2000/svg","path");
  wp.setAttribute("class","water-body"); wp.setAttribute("d",dd); tgt.appendChild(wp);
});
(function(){
  var g=document.createElementNS("http://www.w3.org/2000/svg","g");
  g.setAttribute("transform","rotate(-10,400,390)");
  g.setAttribute("pointer-events","none");
  var t1=document.createElementNS("http://www.w3.org/2000/svg","text");
  t1.setAttribute("x","400"); t1.setAttribute("y","388");
  t1.setAttribute("text-anchor","middle");
  t1.setAttribute("font-size","14"); t1.setAttribute("font-family","Inter Tight,sans-serif");
  t1.setAttribute("font-weight","500"); t1.setAttribute("fill","#162138");
  t1.setAttribute("opacity","0.5"); t1.setAttribute("letter-spacing","1.5");
  t1.textContent="Невская"; g.appendChild(t1);
  var t2=document.createElementNS("http://www.w3.org/2000/svg","text");
  t2.setAttribute("x","408"); t2.setAttribute("y","406");
  t2.setAttribute("text-anchor","middle");
  t2.setAttribute("font-size","14"); t2.setAttribute("font-family","Inter Tight,sans-serif");
  t2.setAttribute("font-weight","500"); t2.setAttribute("fill","#162138");
  t2.setAttribute("opacity","0.5"); t2.setAttribute("letter-spacing","1.5");
  t2.textContent="губа"; g.appendChild(t2);
  tgt.appendChild(g);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Василеостровский');
  el.setAttribute("d",'M 531.4,375.2 L 513.7,383.6 L 505.8,412.4 L 523.9,435.7 L 561.8,449.9 L 568.3,451.5 L 572.3,449.5 L 576.8,432.1 L 580.7,427.3 L 586.7,423.7 L 598.1,417.4 L 602.2,413.2 L 604.2,411.0 L 603.2,409.3 L 599.8,408.5 L 592.3,406.8 L 585.5,403.2 L 570.8,391.4 L 538.0,375.6 L 531.4,375.2 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Невский');
  el.setAttribute("d",'M 724.1,591.9 L 748.3,632.2 L 748.1,629.8 L 750.4,624.1 L 756.0,616.9 L 756.7,613.2 L 757.1,610.6 L 776.9,626.6 L 780.3,619.4 L 784.6,614.8 L 787.8,610.8 L 787.3,609.6 L 783.1,604.7 L 782.2,597.5 L 782.8,593.1 L 782.5,590.1 L 780.7,589.1 L 778.2,590.3 L 775.0,592.7 L 771.6,594.2 L 765.4,594.8 L 760.1,592.1 L 754.5,586.7 L 750.8,582.1 L 748.6,579.7 L 744.4,577.2 L 741.5,576.8 L 735.1,575.3 L 732.7,570.9 L 732.6,566.2 L 732.2,563.0 L 733.5,559.7 L 734.7,555.0 L 734.5,551.7 L 732.2,547.7 L 729.0,542.0 L 726.2,538.0 L 722.2,535.4 L 715.9,534.4 L 710.1,530.2 L 705.9,520.5 L 701.3,510.3 L 700.1,500.1 L 697.9,491.1 L 693.6,480.9 L 687.3,473.4 L 677.9,465.9 L 674.0,459.5 L 669.2,451.7 L 651.8,458.7 L 643.7,460.3 L 645.4,465.3 L 653.8,476.9 L 662.0,490.8 L 686.8,534.7 L 700.3,553.9 L 709.6,567.8 L 710.7,573.3 L 712.1,572.3 L 724.1,591.9 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Петроградский');
  el.setAttribute("d",'M 533.9,357.9 L 533.0,365.6 L 535.3,367.9 L 552.9,377.9 L 574.0,388.7 L 592.5,403.1 L 603.3,403.9 L 608.9,405.0 L 625.1,393.5 L 623.3,381.9 L 621.7,371.7 L 617.0,359.5 L 608.8,352.5 L 594.8,347.3 L 585.5,348.4 L 581.7,349.8 L 578.7,349.6 L 566.9,348.8 L 555.8,350.2 L 548.3,352.8 L 540.1,354.5 L 533.9,357.9 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Фрунзенский');
  el.setAttribute("d",'M 623.6,467.2 L 625.6,472.1 L 627.3,479.8 L 630.9,495.5 L 630.5,505.2 L 632.9,514.7 L 636.7,523.9 L 643.9,558.1 L 656.5,615.6 L 709.7,594.4 L 723.3,590.7 L 711.8,571.6 L 710.0,572.6 L 708.7,566.6 L 696.5,548.3 L 688.0,537.0 L 677.7,520.0 L 666.7,499.1 L 654.2,477.3 L 645.1,465.5 L 643.2,460.3 L 639.3,459.8 L 631.0,456.8 L 627.9,456.6 L 623.1,460.1 L 623.6,467.2 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Невский');
  el.setAttribute("d",'M 756.0,542.9 L 737.9,495.4 L 744.8,428.9 L 716.2,425.0 L 706.9,421.8 L 703.4,422.9 L 700.2,430.2 L 687.7,449.4 L 678.9,454.8 L 681.8,461.5 L 688.9,468.0 L 692.6,472.8 L 698.0,480.8 L 702.0,489.4 L 703.3,495.8 L 705.1,508.4 L 708.8,518.1 L 712.8,526.7 L 714.6,528.1 L 719.4,530.5 L 723.1,530.9 L 725.5,531.5 L 728.5,533.0 L 730.9,537.0 L 733.1,540.4 L 735.2,541.8 L 737.4,546.1 L 738.8,549.6 L 739.1,550.3 L 743.3,549.4 L 746.9,549.0 L 747.3,546.2 L 753.1,544.9 L 756.0,542.9 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Адмиралтейский');
  el.setAttribute("d",'M 564.6,482.2 L 565.7,481.7 L 568.7,482.5 L 570.7,482.5 L 572.2,481.7 L 573.2,479.3 L 574.6,479.2 L 575.8,478.6 L 577.8,479.6 L 578.7,479.2 L 579.4,479.8 L 579.1,480.4 L 579.4,481.0 L 580.3,481.7 L 586.5,476.5 L 587.8,477.4 L 591.0,477.7 L 595.0,477.9 L 596.4,478.7 L 595.5,488.9 L 597.8,489.0 L 611.3,488.3 L 610.9,468.4 L 612.9,468.0 L 626.6,456.5 L 627.0,455.7 L 628.3,454.3 L 622.9,444.3 L 623.3,443.8 L 619.1,439.4 L 617.1,441.2 L 604.9,422.5 L 607.4,420.3 L 605.9,418.1 L 604.4,416.2 L 602.6,418.0 L 591.7,427.7 L 584.4,431.2 L 580.3,433.9 L 576.0,450.2 L 571.5,457.3 L 570.7,461.8 L 569.1,466.9 L 567.1,471.7 L 562.8,480.4 L 564.6,482.2 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Выборгский');
  el.setAttribute("d",'M 614.2,352.4 L 619.3,357.7 L 624.3,370.7 L 625.3,382.6 L 628.5,392.8 L 632.2,394.4 L 633.5,394.0 L 636.3,384.1 L 634.6,378.4 L 632.3,363.6 L 629.1,355.1 L 641.4,352.0 L 644.9,354.6 L 646.0,354.7 L 644.9,349.8 L 642.5,344.3 L 635.0,335.2 L 635.3,332.7 L 641.4,327.1 L 643.6,324.0 L 644.9,315.6 L 647.8,306.1 L 645.9,287.2 L 644.1,264.9 L 644.3,261.4 L 645.3,258.3 L 660.9,221.2 L 653.1,187.3 L 650.1,185.4 L 645.9,166.2 L 621.5,169.6 L 602.8,159.7 L 599.9,167.9 L 591.8,164.2 L 591.5,158.9 L 588.3,159.4 L 579.7,148.4 L 580.2,138.9 L 576.3,134.6 L 577.0,125.9 L 573.0,120.3 L 573.0,114.6 L 567.4,111.0 L 552.1,122.0 L 544.7,123.9 L 539.8,127.0 L 531.2,125.1 L 515.9,124.2 L 516.7,129.8 L 515.2,130.1 L 504.4,132.9 L 436.4,123.9 L 432.0,182.5 L 471.1,243.4 L 478.3,237.8 L 519.4,212.4 L 523.1,217.8 L 526.5,214.7 L 532.7,218.3 L 535.9,216.6 L 542.3,231.6 L 551.6,225.4 L 579.0,204.8 L 588.2,222.8 L 590.7,227.4 L 593.0,231.6 L 594.2,234.8 L 597.1,247.4 L 600.1,259.9 L 603.1,272.6 L 604.6,279.3 L 611.0,306.2 L 613.2,315.0 L 614.6,321.2 L 618.2,327.2 L 616.6,328.3 L 617.6,330.2 L 619.0,337.7 L 619.6,342.6 L 619.1,344.3 L 620.0,346.3 L 614.2,352.4 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Калининский');
  el.setAttribute("d",'M 659.9,222.0 L 644.6,261.6 L 644.4,265.5 L 648.2,306.1 L 645.4,315.5 L 643.9,323.9 L 641.7,327.0 L 635.2,333.0 L 635.0,335.2 L 642.6,344.4 L 645.2,349.7 L 646.3,354.7 L 644.9,354.8 L 641.3,352.1 L 629.5,355.0 L 631.9,362.9 L 633.7,369.5 L 636.4,383.3 L 633.6,394.2 L 633.7,394.9 L 642.9,396.2 L 651.5,392.4 L 657.6,385.6 L 665.4,385.1 L 670.8,388.3 L 674.4,385.2 L 678.1,364.6 L 693.2,331.9 L 699.8,317.7 L 695.1,293.1 L 696.4,285.7 L 695.7,282.2 L 696.6,249.4 L 686.5,244.3 L 679.9,239.5 L 681.9,235.0 L 659.9,222.0 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Кировский');
  el.setAttribute("d",'M 561.5,455.2 L 549.7,458.1 L 535.8,454.6 L 530.4,468.1 L 522.1,491.9 L 514.8,496.8 L 507.8,502.0 L 504.0,500.6 L 503.1,505.1 L 511.0,518.2 L 524.7,534.2 L 526.3,532.3 L 529.0,535.3 L 537.2,540.7 L 554.3,541.2 L 522.1,592.9 L 514.2,608.1 L 514.7,608.7 L 525.0,609.7 L 533.6,608.3 L 544.0,606.0 L 553.8,601.2 L 572.8,590.9 L 575.8,588.2 L 578.8,583.7 L 584.7,574.4 L 588.9,564.6 L 590.0,556.9 L 590.6,549.4 L 592.6,519.8 L 593.5,516.9 L 595.3,514.6 L 597.6,512.9 L 597.8,511.3 L 593.4,511.2 L 594.8,494.7 L 595.1,489.0 L 596.3,479.0 L 594.8,478.1 L 592.0,478.2 L 587.9,477.5 L 586.6,476.5 L 580.3,481.8 L 579.4,481.0 L 579.1,480.3 L 579.2,479.8 L 578.6,479.4 L 577.8,479.7 L 575.7,478.8 L 574.5,479.4 L 573.2,479.5 L 572.5,481.7 L 570.4,482.8 L 568.5,482.6 L 565.8,481.8 L 564.5,482.5 L 562.4,480.4 L 568.4,468.0 L 570.3,461.9 L 570.1,456.7 L 569.5,455.3 L 561.5,455.2 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Колпинский');
  el.setAttribute("d",'M 707.2,617.7 L 737.0,654.4 L 752.8,679.1 L 746.8,703.9 L 748.2,714.8 L 744.2,733.6 L 781.5,729.5 L 783.4,752.0 L 789.8,760.2 L 796.9,761.7 L 804.8,761.7 L 806.4,763.9 L 811.8,764.1 L 817.0,761.1 L 825.0,760.5 L 824.4,752.7 L 834.3,752.0 L 847.9,775.8 L 872.7,770.6 L 869.3,759.5 L 871.5,757.7 L 881.0,737.9 L 887.1,734.3 L 893.5,734.0 L 924.1,739.0 L 919.9,729.6 L 919.5,727.2 L 920.5,725.9 L 924.3,725.1 L 927.0,724.1 L 927.3,721.2 L 925.2,719.2 L 919.8,720.4 L 915.9,719.4 L 910.8,713.4 L 913.4,704.7 L 909.5,697.7 L 904.5,695.2 L 905.7,691.3 L 908.7,685.1 L 907.5,684.0 L 903.1,682.8 L 896.9,681.9 L 892.7,682.2 L 883.1,682.5 L 876.8,678.5 L 871.8,675.3 L 867.9,674.8 L 860.7,670.7 L 851.7,665.3 L 842.4,664.5 L 833.1,661.1 L 825.0,651.9 L 817.8,641.2 L 812.0,637.4 L 807.7,628.5 L 805.3,623.9 L 801.5,619.8 L 798.0,617.2 L 794.0,614.1 L 787.7,611.2 L 786.7,613.0 L 783.8,615.3 L 781.8,614.3 L 780.8,615.7 L 782.2,617.3 L 779.9,619.7 L 776.5,625.7 L 756.7,609.5 L 755.7,616.1 L 750.0,623.8 L 747.8,628.9 L 748.1,631.8 L 723.1,591.0 L 710.7,594.2 L 700.9,598.3 L 707.2,617.7 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Красногвардейский');
  el.setAttribute("d",'M 695.9,282.5 L 696.7,285.4 L 695.5,293.4 L 699.8,317.7 L 678.4,364.8 L 675.1,385.3 L 672.5,390.0 L 674.2,396.9 L 672.5,412.9 L 668.6,432.6 L 669.3,438.3 L 673.2,446.2 L 679.0,454.5 L 688.0,449.0 L 696.4,436.1 L 700.2,430.0 L 703.4,422.8 L 706.1,421.5 L 714.7,424.6 L 753.5,430.0 L 758.7,382.4 L 765.6,369.1 L 775.0,361.2 L 778.7,368.6 L 785.3,367.0 L 788.3,366.2 L 783.4,361.7 L 782.0,362.5 L 781.4,361.7 L 782.6,360.8 L 781.5,359.9 L 779.8,355.1 L 779.6,352.1 L 777.8,352.1 L 777.8,353.8 L 775.4,353.1 L 775.7,350.3 L 770.5,348.5 L 767.6,346.5 L 765.2,346.2 L 763.7,347.9 L 761.2,346.8 L 762.9,345.6 L 763.1,343.5 L 764.2,344.1 L 764.2,342.3 L 764.8,339.3 L 766.2,340.5 L 768.2,337.4 L 767.5,333.7 L 765.5,330.3 L 745.8,341.6 L 747.0,338.5 L 746.6,334.6 L 745.8,329.8 L 743.8,327.8 L 743.6,323.6 L 742.6,318.7 L 739.9,316.8 L 743.4,313.1 L 743.6,306.9 L 739.7,306.3 L 736.7,302.4 L 733.8,303.2 L 731.5,294.5 L 733.5,288.0 L 732.5,280.6 L 728.6,284.3 L 726.9,281.2 L 724.2,280.1 L 722.7,275.5 L 718.0,279.8 L 715.8,275.8 L 718.3,272.1 L 714.6,271.3 L 716.0,267.1 L 718.3,264.8 L 718.5,262.0 L 715.3,262.6 L 710.9,254.1 L 707.4,255.8 L 702.5,253.2 L 701.5,249.0 L 699.1,249.2 L 696.6,251.3 L 695.9,282.5 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Красносельский');
  el.setAttribute("d",'M 464.4,821.0 L 464.6,821.1 L 464.7,820.9 L 464.4,821.0 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Красносельский');
  el.setAttribute("d",'M 461.7,776.5 L 461.2,771.9 L 459.1,764.0 L 461.0,748.3 L 466.2,741.6 L 467.7,736.3 L 467.9,731.2 L 465.2,718.6 L 467.0,710.4 L 484.9,711.0 L 490.6,693.4 L 485.7,687.4 L 493.3,672.0 L 497.0,666.6 L 498.2,657.8 L 494.3,655.0 L 490.8,664.1 L 487.4,661.2 L 497.4,645.5 L 509.3,654.0 L 511.2,657.5 L 509.7,660.9 L 511.5,662.0 L 518.1,660.6 L 521.6,656.3 L 526.7,654.3 L 532.9,651.5 L 536.6,650.6 L 540.3,641.0 L 544.9,625.3 L 544.2,608.0 L 545.7,605.4 L 524.3,609.7 L 514.4,607.7 L 521.8,592.7 L 529.2,581.0 L 554.1,541.6 L 536.6,540.4 L 530.7,537.3 L 526.2,532.8 L 524.0,535.0 L 511.0,519.2 L 504.3,508.4 L 476.1,528.0 L 452.6,537.8 L 452.3,554.4 L 452.6,556.9 L 454.1,558.0 L 453.8,558.6 L 451.1,558.1 L 447.0,560.2 L 447.8,587.4 L 443.8,589.3 L 432.6,583.8 L 436.6,622.0 L 443.3,620.4 L 448.1,623.1 L 456.8,619.1 L 474.0,632.5 L 470.8,640.1 L 457.7,642.5 L 458.3,650.3 L 457.4,652.3 L 452.9,653.6 L 452.3,663.8 L 453.5,669.9 L 452.6,672.2 L 451.8,675.2 L 448.0,675.9 L 445.3,679.6 L 442.6,679.6 L 442.3,687.3 L 423.8,701.8 L 413.0,706.3 L 413.7,709.3 L 423.9,707.6 L 424.0,710.3 L 425.6,709.9 L 427.1,718.0 L 433.7,718.4 L 434.0,720.8 L 430.5,720.8 L 430.0,726.7 L 436.7,732.8 L 427.3,743.0 L 422.1,753.5 L 422.0,753.6 L 422.6,756.3 L 418.8,761.5 L 418.5,765.0 L 416.5,769.4 L 416.4,772.7 L 415.3,779.6 L 410.1,777.4 L 407.4,782.5 L 412.3,785.9 L 418.7,783.3 L 421.7,791.3 L 435.3,783.8 L 435.7,786.1 L 438.3,784.6 L 440.9,785.8 L 442.7,792.5 L 454.8,812.8 L 459.0,813.0 L 460.8,811.1 L 463.5,813.4 L 465.5,812.8 L 464.9,817.0 L 465.0,819.4 L 464.7,820.9 L 467.8,820.4 L 468.4,824.7 L 471.5,824.7 L 475.2,822.7 L 480.0,817.0 L 480.4,813.0 L 479.1,809.6 L 480.2,808.9 L 483.8,800.7 L 477.8,800.9 L 471.4,800.3 L 470.8,796.5 L 468.7,798.5 L 463.4,790.8 L 464.7,789.3 L 462.8,784.6 L 461.7,776.5 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Кронштадтский');
  el.setAttribute("d",'M 101.3,249.0 L 130.8,294.1 L 156.5,332.6 L 241.1,368.8 L 264.8,346.1 L 245.1,303.2 L 201.6,253.6 L 134.8,233.2 L 101.3,249.0 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Курортный');
  el.setAttribute("d",'M 86.3,1.2 L 191.7,24.8 L 268.9,57.4 L 286.2,55.1 L 323.1,88.3 L 324.6,146.9 L 306.4,153.6 L 333.0,214.5 L 341.3,242.7 L 361.6,246.6 L 365.2,245.0 L 367.1,257.3 L 395.3,284.3 L 405.9,289.2 L 409.3,296.9 L 429.0,304.3 L 433.9,281.1 L 471.3,243.3 L 432.4,182.9 L 436.4,125.1 L 504.4,132.1 L 516.4,130.4 L 515.0,117.7 L 507.3,110.4 L 506.1,100.0 L 468.7,103.4 L 396.5,80.4 L 396.5,69.7 L 390.1,54.0 L 375.8,47.2 L 368.9,33.2 L 352.6,27.6 L 330.0,17.4 L 308.3,5.1 L 305.4,-3.3 L 286.7,-5.0 L 276.8,-5.6 L 269.9,-15.7 L 262.1,-16.3 L 248.8,-23.6 L 240.9,-44.9 L 236.0,-46.7 L 231.5,-49.4 L 222.2,-56.7 L 217.7,-66.2 L 199.0,-81.4 L 192.1,-77.4 L 174.9,-79.1 L 177.4,-65.7 L 183.8,-55.6 L 176.9,-55.6 L 164.1,-73.0 L 150.8,-73.5 L 139.5,-78.0 L 127.2,-75.2 L 121.2,-67.3 L 109.4,-72.4 L 98.1,-69.0 L 87.3,-58.4 L 85.3,-45.5 L 60.2,-52.8 L 51.3,-51.1 L 51.3,-44.3 L 40.5,-51.6 L 40.5,-66.2 L 22.3,-46.6 L 15.9,-54.4 L -31.4,2.3 L -15.1,4.5 L -9.7,11.8 L 0.6,12.4 L 4.1,18.6 L -11.7,20.3 L -23.0,28.7 L 4.6,41.1 L 86.3,1.2 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Московский');
  el.setAttribute("d",'M 593.0,511.0 L 597.3,511.0 L 597.3,512.7 L 595.2,514.1 L 592.9,518.0 L 588.8,564.6 L 585.0,574.6 L 575.0,589.1 L 545.7,605.1 L 544.1,608.2 L 544.9,625.0 L 540.6,640.5 L 536.1,650.7 L 575.4,663.8 L 576.3,655.5 L 584.6,654.0 L 588.2,660.0 L 588.6,662.1 L 576.4,681.6 L 578.7,683.8 L 575.1,688.7 L 573.9,688.1 L 568.5,692.2 L 567.0,695.3 L 562.3,700.9 L 560.2,702.0 L 604.7,738.2 L 618.8,706.3 L 621.5,698.4 L 621.3,692.5 L 617.6,687.4 L 616.2,684.1 L 616.0,661.8 L 617.3,659.8 L 617.8,655.8 L 615.1,651.1 L 615.5,641.3 L 616.1,641.0 L 618.8,640.4 L 620.7,638.0 L 623.9,636.5 L 624.9,633.8 L 627.6,632.1 L 628.5,629.4 L 632.1,626.7 L 637.9,623.2 L 644.4,621.3 L 647.4,618.8 L 656.5,615.9 L 647.5,574.7 L 636.3,523.7 L 632.1,513.7 L 630.5,504.6 L 630.5,496.0 L 627.6,483.3 L 625.7,473.8 L 623.6,467.8 L 623.5,462.5 L 622.6,459.5 L 613.0,468.0 L 610.9,468.6 L 611.3,488.2 L 595.4,489.3 L 593.0,511.0 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Петродворцовый');
  el.setAttribute("d",'M 263.7,535.4 L 272.0,532.9 L 282.7,545.5 L 281.9,547.7 L 283.3,551.1 L 283.9,555.7 L 287.6,558.4 L 290.3,554.5 L 290.9,550.0 L 297.2,560.2 L 294.1,568.3 L 296.1,568.3 L 296.5,574.5 L 300.9,576.5 L 305.6,558.2 L 308.9,560.2 L 309.6,558.9 L 313.3,559.6 L 312.3,564.6 L 317.5,566.3 L 318.4,562.1 L 329.4,565.0 L 329.1,568.3 L 343.1,574.0 L 337.4,596.5 L 340.9,596.4 L 342.7,599.2 L 366.4,591.0 L 366.7,589.2 L 377.2,592.0 L 384.7,586.6 L 386.8,586.9 L 392.1,587.2 L 393.1,589.6 L 394.7,587.5 L 397.0,592.0 L 404.2,585.2 L 414.4,585.9 L 412.7,593.0 L 410.6,596.1 L 410.4,605.2 L 409.2,610.2 L 416.2,617.9 L 424.2,618.7 L 436.5,621.7 L 433.0,583.8 L 443.9,589.0 L 447.7,587.0 L 447.1,560.6 L 450.3,558.1 L 453.9,557.8 L 452.4,556.8 L 452.4,538.1 L 418.3,532.8 L 389.6,530.8 L 365.6,509.8 L 327.1,494.5 L 298.1,485.0 L 292.3,477.1 L 274.9,475.2 L 267.8,473.0 L 262.1,469.4 L 254.0,461.1 L 249.1,454.1 L 245.4,447.5 L 240.5,440.2 L 234.8,434.0 L 226.7,428.9 L 220.5,426.3 L 212.2,424.3 L 204.3,422.6 L 187.8,417.3 L 170.1,411.6 L 149.4,411.6 L 137.0,428.8 L 144.8,438.3 L 139.7,451.0 L 145.8,459.1 L 173.6,462.0 L 187.0,480.5 L 184.0,495.2 L 179.9,513.7 L 196.4,530.3 L 204.5,530.3 L 216.4,529.7 L 231.6,540.3 L 251.1,552.7 L 263.7,535.4 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Приморский');
  el.setAttribute("d",'M 613.6,353.4 L 619.5,346.6 L 619.1,344.4 L 619.6,342.3 L 617.7,330.1 L 616.4,328.3 L 618.3,327.1 L 614.3,320.8 L 606.3,286.5 L 596.0,243.4 L 592.6,231.0 L 588.2,223.2 L 578.2,204.8 L 542.5,232.4 L 535.9,217.5 L 532.2,218.6 L 526.5,215.5 L 522.8,218.1 L 519.1,213.0 L 476.8,238.4 L 434.5,281.0 L 428.9,304.4 L 413.0,298.3 L 409.6,296.9 L 405.4,288.9 L 395.3,284.6 L 367.0,257.3 L 364.8,245.3 L 361.7,246.8 L 341.7,243.4 L 342.3,258.3 L 351.7,305.0 L 388.2,334.9 L 424.6,328.7 L 503.4,346.4 L 522.9,351.7 L 529.9,354.0 L 538.4,349.8 L 542.5,348.2 L 544.1,348.7 L 546.1,349.9 L 549.0,349.1 L 553.5,347.5 L 568.2,346.1 L 573.8,346.7 L 577.1,347.8 L 580.4,347.6 L 585.2,345.9 L 590.5,344.5 L 595.3,345.1 L 609.5,349.7 L 613.6,353.4 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Пушкинский');
  el.setAttribute("d",'M 711.6,902.6 L 715.4,909.3 L 717.0,911.7 L 719.9,910.6 L 723.3,911.0 L 726.5,914.3 L 728.4,911.7 L 730.6,910.8 L 730.6,908.1 L 732.8,906.7 L 733.0,905.1 L 737.6,902.8 L 739.2,903.0 L 743.6,900.6 L 743.7,887.7 L 743.0,880.7 L 742.4,863.2 L 736.0,861.2 L 734.5,860.7 L 739.8,848.7 L 734.8,845.9 L 733.3,838.2 L 731.3,836.3 L 732.4,831.2 L 757.7,821.9 L 757.0,818.9 L 755.4,817.4 L 756.9,813.0 L 758.6,811.0 L 758.9,806.3 L 762.2,804.0 L 763.2,799.8 L 771.5,800.9 L 787.4,802.8 L 796.8,761.4 L 795.0,761.2 L 789.7,760.4 L 783.2,752.2 L 782.0,730.0 L 758.8,732.7 L 744.3,733.7 L 748.2,716.6 L 748.1,701.6 L 753.7,680.0 L 739.1,658.2 L 715.7,628.4 L 707.0,617.2 L 700.5,598.3 L 688.0,603.1 L 656.6,616.1 L 647.5,619.0 L 644.2,621.7 L 637.5,624.0 L 628.8,629.1 L 628.0,632.1 L 625.1,633.8 L 624.0,636.8 L 620.3,639.2 L 619.1,640.6 L 615.7,641.6 L 615.6,651.0 L 617.7,655.9 L 617.2,659.1 L 615.0,661.6 L 615.6,683.2 L 616.6,686.5 L 619.4,690.2 L 621.0,693.9 L 618.7,706.7 L 604.5,738.0 L 598.4,733.0 L 593.1,744.8 L 592.2,750.8 L 588.3,757.5 L 585.3,759.1 L 586.0,763.5 L 578.2,773.6 L 577.5,777.3 L 583.0,780.6 L 580.4,786.9 L 575.6,784.6 L 574.8,788.4 L 569.0,799.7 L 565.9,808.4 L 562.9,809.8 L 550.7,822.9 L 552.4,824.9 L 549.9,827.7 L 548.7,829.1 L 552.2,834.8 L 546.9,837.9 L 539.7,855.9 L 542.4,859.9 L 546.8,862.0 L 545.7,858.9 L 547.1,855.3 L 551.4,856.3 L 556.8,859.7 L 561.2,859.0 L 561.8,860.2 L 553.2,875.3 L 556.0,876.1 L 555.9,880.0 L 557.3,888.3 L 563.8,889.3 L 569.3,896.0 L 557.0,912.3 L 564.8,920.5 L 602.3,874.0 L 616.6,883.2 L 624.0,880.6 L 634.6,880.3 L 634.7,884.7 L 645.4,893.3 L 654.5,894.4 L 659.1,898.1 L 663.2,894.0 L 666.5,890.7 L 669.0,893.3 L 670.3,891.9 L 673.5,896.0 L 674.9,897.1 L 685.0,882.6 L 686.4,873.0 L 694.5,872.6 L 711.6,902.6 Z');
  tgt.appendChild(el);
})();
(function(){
  var el=document.createElementNS("http://www.w3.org/2000/svg","path");
  el.setAttribute("class","map-district");
  el.setAttribute("data-name",'Центральный');
  el.setAttribute("d",'M 607.5,420.3 L 605.2,422.4 L 617.1,440.7 L 619.4,439.4 L 623.7,443.5 L 623.0,444.1 L 628.5,453.9 L 626.7,456.5 L 630.1,456.0 L 642.2,459.4 L 651.0,458.0 L 667.1,450.3 L 661.5,436.3 L 668.2,411.5 L 669.5,397.8 L 667.4,394.2 L 663.1,390.4 L 658.7,390.5 L 653.8,395.2 L 646.1,399.9 L 631.2,400.5 L 615.0,408.6 L 605.6,416.0 L 604.9,416.6 L 607.5,420.3 Z');
  tgt.appendChild(el);
})();
var loader = document.getElementById('map-loading');
if (loader) loader.style.display = 'none';
document.getElementById('map-svg').style.opacity = '1';
initMapDistricts();
}
function _blockScroll(e) { e.preventDefault(); }
function openMapPopup() {
var overlay = document.getElementById('map-popup-overlay');
var popup = document.getElementById('map-popup');
overlay.classList.add('active');
setTimeout(function(){ popup.classList.add('active'); }, 10);
document.body.style.overflow = 'hidden';
document.body.addEventListener('touchmove', _blockScroll, {passive: false});
// Позиция компаса: на десктопе — правый нижний угол, на мобиле — правый верхний
var compass = document.querySelector('.map-compass');
if (compass) {
  if (window.innerWidth > 900) {
    compass.style.display = 'none';
  } else {
    compass.style.top = '';
    compass.style.bottom = '';
    compass.style.right = '';
  }
}
loadMapSVG();
}
function closeMapPopup() {
var overlay = document.getElementById('map-popup-overlay');
var popup = document.getElementById('map-popup');
popup.classList.remove('active');
setTimeout(function(){ overlay.classList.remove('active'); }, 350);
document.body.style.overflow = '';
document.body.removeEventListener('touchmove', _blockScroll);
}
function applyMapDistricts() {
closeMapPopup();
if (typeof filterApartments === 'function') filterApartments();
}
function resetMapDistricts() {
selectedMapDistricts = [];
document.querySelectorAll('.map-district.selected').forEach(el => el.classList.remove('selected'));
updateMapUI();
if (typeof filterApartments === 'function') filterApartments();
}
function declOfNum(n, f) { n = Math.abs(n) % 100; var n1 = n % 10; if (n > 10 && n < 20) return f[2]; if (n1 > 1 && n1 < 5) return f[1]; if (n1 === 1) return f[0]; return f[2]; }
function countByDistricts(districts) {
  if (!districts.length) return apartmentsData.length;
  return apartmentsData.filter(function(apt) {
    return apt.district && districts.some(function(d) { return apt.district.toLowerCase() === d.toLowerCase(); });
  }).length;
}
function updateMapUI() {
const bar    = document.getElementById('map-selected-bar');
const chips  = document.getElementById('map-selected-chips');
const btn    = document.getElementById('map-apply-btn');
const dBtns  = document.querySelectorAll('.m-district-btn');
const cnt    = countByDistricts(selectedMapDistricts);
const tv     = declOfNum(cnt, ['вариант', 'варианта', 'вариантов']);
if (selectedMapDistricts.length > 0) {
bar.classList.add('visible');
chips.innerHTML = selectedMapDistricts.map(d => '<span class="map-selected-chip">' + d + '</span>').join('');
btn.textContent = 'Показать ' + cnt + ' ' + tv;
dBtns.forEach(b => { b.classList.add('has-selection'); b.textContent = selectedMapDistricts.join(', '); });
} else {
bar.classList.remove('visible');
chips.innerHTML = '';
btn.textContent = 'Показать ' + cnt + ' ' + tv;
dBtns.forEach(b => { b.classList.remove('has-selection'); b.textContent = 'Выбрать район'; });
}
}
document.getElementById('map-popup-overlay').addEventListener('click', function(e) {
if (e.target === this) closeMapPopup();
});
function initMapDistricts() {
var hovered = null;
var svg = document.getElementById('map-svg');
var wrap = svg.parentElement;
var scale = 1.7, tx = 0, ty = 0;
var pinching = false, lastDist = 0;
var touchStartX = 0, touchStartY = 0, touchMoved = false;

function getSvgSize() {
  // SVG 100%x100% враппера, viewBox 900:823 — letterboxed
  var ww = wrap.offsetWidth, wh = wrap.offsetHeight;
  var aspect = 900 / 823;
  if (ww / wh < aspect) {
    return { w: ww, h: ww / aspect };
  } else {
    return { w: wh * aspect, h: wh };
  }
}
function applyTransform() {
  var ww = wrap.offsetWidth, wh = wrap.offsetHeight;
  var s = getSvgSize();
  var scaledW = s.w * scale;
  if (scaledW > ww) tx = Math.min(0, Math.max(ww - scaledW, tx));
  svg.style.transform = 'translate('+tx+'px,'+ty+'px) scale('+scale+')';
  svg.style.transformOrigin = '0 0';
}
function centerMap() {
  var ww = wrap.offsetWidth, wh = wrap.offsetHeight;
  if (!ww || !wh) return;
  if (window.innerWidth > 900) {
    var fitByW = ww / 900;
    var fitByH = wh / 823;
    scale = Math.min(fitByW, fitByH) * 0.95;
    var s = getSvgSize();
    var scaledW = s.w * scale, scaledH = s.h * scale;
    // Центрируем по горизонтали, по вертикали — центр Василеостровского (490, 430 в SVG)
    var vasX = (490 / 900) * scaledW;
    var vasY = (430 / 823) * scaledH;
    tx = ww / 2 - vasX;
    ty = wh / 2 - vasY - 25;
  } else {
    // Мобильная: оригинальная логика не тронута
    var s = getSvgSize();
    var svgOffsetX = (ww - s.w) / 2;
    var svgOffsetY = (wh - s.h) / 2;
    tx = ww/2 - svgOffsetX - (556.3/900)*s.w*scale + 10;
    ty = wh/2 - svgOffsetY - (409.9/823)*s.h*scale - 150;
  }
  // Стартовые значения для анимации (уменьшенная версия)
  var s0 = scale * 0.55;
  var cx = ww/2, cy = wh/2;
  var tx0 = cx - (cx - tx) * (s0/scale);
  var ty0 = cy - (cy - ty) * (s0/scale);
  svg.style.setProperty('--tx0', tx0+'px');
  svg.style.setProperty('--ty0', ty0+'px');
  svg.style.setProperty('--s0', s0);
  svg.style.setProperty('--tx1', tx+'px');
  svg.style.setProperty('--ty1', ty+'px');
  svg.style.setProperty('--s1', scale);
  svg.style.opacity = '1';
  svg.classList.add('animating');
  svg.addEventListener('animationend', function() {
    svg.classList.remove('animating');
    svg.style.transform = 'translate('+tx+'px,'+ty+'px) scale('+scale+')';
    svg.style.transformOrigin = '0 0';
  }, {once: true});
}
setTimeout(centerMap, 80);
svg.style.transition = 'none';
wrap.style.touchAction = 'none';

// Desktop: scroll zoom
if (window.matchMedia('(hover: hover)').matches) {
  wrap.addEventListener('wheel', function(e) {
    e.preventDefault();
    var rect = wrap.getBoundingClientRect();
    var ox = e.clientX - rect.left;
    var oy = e.clientY - rect.top;
    var delta = e.deltaY > 0 ? 0.9 : 1.1;
    var newScale = Math.max(0.3, Math.min(5, scale * delta));
    tx = ox - (ox - tx) * (newScale / scale);
    ty = oy - (oy - ty) * (newScale / scale);
    scale = newScale;
    applyTransform();
  }, { passive: false });

  // Desktop: mouse drag
  var _dragging = false, _dragX = 0, _dragY = 0;
  wrap.addEventListener('mousedown', function(e) {
    if (e.button !== 0) return;
    _dragging = true;
    _dragX = e.clientX; _dragY = e.clientY;
    wrap.style.cursor = 'grabbing';
    hideTip(0);
  });
  window.addEventListener('mousemove', function(e) {
    if (!_dragging) return;
    tx += e.clientX - _dragX;
    ty += e.clientY - _dragY;
    _dragX = e.clientX; _dragY = e.clientY;
    applyTransform();
  });
  window.addEventListener('mouseup', function() {
    if (!_dragging) return;
    _dragging = false;
    wrap.style.cursor = '';
  });
}

// Touch pan + pinch
var activeTouches = {};
wrap.addEventListener('touchstart', function(e) {
  e.preventDefault();
  Array.from(e.changedTouches).forEach(function(t) {
    activeTouches[t.identifier] = {x: t.clientX, y: t.clientY, startX: t.clientX, startY: t.clientY};
  });
  var ids = Object.keys(activeTouches);
  if (ids.length === 2) {
    var a = activeTouches[ids[0]], b = activeTouches[ids[1]];
    lastDist = Math.hypot(b.x-a.x, b.y-a.y);
    pinching = true;
    hideTip(0);
  } else if (ids.length === 1) {
    var t = e.changedTouches[0];
    var rect = wrap.getBoundingClientRect();
    var el = document.elementFromPoint(t.clientX, t.clientY);
    if (!el || !el.classList.contains('map-district')) {
      var svgX = (t.clientX - rect.left - tx) / scale;
      var svgY = (t.clientY - rect.top  - ty) / scale;
      var dlist = wrap.querySelectorAll('.map-district');
      for (var i = 0; i < dlist.length; i++) {
        var bb = dlist[i].getBBox();
        if (svgX >= bb.x && svgX <= bb.x+bb.width && svgY >= bb.y && svgY <= bb.y+bb.height) { el = dlist[i]; break; }
      }
    }
    if (el && el.classList.contains('map-district')) {
      showTip(el.dataset.name, t.clientX, t.clientY - 70);
    }
  }
  touchMoved = false;
}, {passive: false});

wrap.addEventListener('touchmove', function(e) {
  e.preventDefault();
  var ids = Object.keys(activeTouches);
  if (ids.length === 1) {
    var t = e.changedTouches[0];
    var prev = activeTouches[t.identifier];
    if (!prev) return;
    var dx = t.clientX - prev.x, dy = t.clientY - prev.y;
    tx += dx; ty += dy;
    prev.x = t.clientX; prev.y = t.clientY;
    applyTransform();
    if (Math.abs(t.clientX - prev.startX) > 8 || Math.abs(t.clientY - prev.startY) > 8) { touchMoved = true; hideTip(0); }
  } else if (ids.length >= 2 && pinching) {
    Array.from(e.changedTouches).forEach(function(t) { if (activeTouches[t.identifier]) { activeTouches[t.identifier].x = t.clientX; activeTouches[t.identifier].y = t.clientY; } });
    var a = activeTouches[ids[0]], b = activeTouches[ids[1]];
    var dist = Math.hypot(b.x-a.x, b.y-a.y);
    var mid = {x:(a.x+b.x)/2, y:(a.y+b.y)/2};
    var rect = wrap.getBoundingClientRect();
    var ox = mid.x - rect.left, oy = mid.y - rect.top;
    var newScale = Math.min(5, Math.max(1, scale * dist / lastDist));
    tx = ox - (ox - tx) * (newScale / scale);
    ty = oy - (oy - ty) * (newScale / scale);
    scale = newScale;
    lastDist = dist;
    applyTransform();
    touchMoved = true;
  }
}, {passive: false});

wrap.addEventListener('touchend', function(e) {
  var t = e.changedTouches[0];
  if (!touchMoved && !pinching) {
    // Используем wrap.getBoundingClientRect для точных координат на реальном мобильном
    var rect = wrap.getBoundingClientRect();
    var cx = t.clientX, cy = t.clientY;
    // Проверяем элемент через document.elementFromPoint
    var el = document.elementFromPoint(cx, cy);
    // Если не попали (из-за скролла страницы) — ищем по SVG координатам
    if (!el || !el.classList.contains('map-district')) {
      var svgX = (cx - rect.left - tx) / scale;
      var svgY = (cy - rect.top - ty) / scale;
      var districts = wrap.querySelectorAll('.map-district');
      for (var i = 0; i < districts.length; i++) {
        var bb = districts[i].getBBox();
        if (svgX >= bb.x && svgX <= bb.x+bb.width && svgY >= bb.y && svgY <= bb.y+bb.height) {
          el = districts[i]; break;
        }
      }
    }
    if (el && el.classList.contains('map-district')) {
      toggleDistrict(el);
      showTip(el.dataset.name, cx, cy - 70);
      hideTip(1500);
      // блокируем фантомный click который браузер генерирует после touchend
      window._touchJustFired = true;
      setTimeout(function() { window._touchJustFired = false; }, 500);
    }
  }
  Array.from(e.changedTouches).forEach(function(t) { delete activeTouches[t.identifier]; });
  if (Object.keys(activeTouches).length < 2) pinching = false;
  if (Object.keys(activeTouches).length === 0) touchMoved = false;
});

// ── Тултип: один div, создаётся один раз ──────────────────────────
var _tip = document.createElement('div');
_tip.id = 'district-tooltip';
_tip.style.cssText = 'position:fixed;transform:translate(-50%,-100%);background:#162138;color:#fff;font-family:Inter Tight,sans-serif;font-size:13px;font-weight:600;padding:6px 14px;border-radius:20px;pointer-events:none;white-space:nowrap;opacity:0;transition:opacity 0.15s ease;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,0.25);display:none';
document.body.appendChild(_tip);

function showTip(name, x, y) {
  clearTimeout(window._tipTimer);
  _tip.textContent = name;
  _tip.style.left = x + 'px';
  _tip.style.top  = y + 'px';
  _tip.style.display = 'block';
  requestAnimationFrame(function() { _tip.style.opacity = '1'; });
}
function hideTip(delay) {
  clearTimeout(window._tipTimer);
  if (!delay) { _tip.style.opacity = '0'; setTimeout(function(){ _tip.style.display='none'; }, 150); return; }
  window._tipTimer = setTimeout(function() { _tip.style.opacity = '0'; setTimeout(function(){ _tip.style.display='none'; }, 150); }, delay);
}

function toggleDistrict(el) {
  var name = el.dataset.name;
  var idx = selectedMapDistricts.indexOf(name);
  var parts = wrap.querySelectorAll('.map-district[data-name="' + name + '"]');
  if (idx > -1) {
    selectedMapDistricts.splice(idx, 1);
    parts.forEach(function(p) { p.classList.remove('selected'); });
  } else {
    selectedMapDistricts.push(name);
    parts.forEach(function(p) { p.classList.add('selected'); });
  }
  updateMapUI();
  if (typeof window.filterApartments === 'function') window.filterApartments();
}

document.querySelectorAll('#map-svg .map-district').forEach(function(el) {
  // click — только для десктопа (на мобильном используется touchend)
  el.addEventListener('click', function(e) {
    if (window._touchJustFired) return; // защита от фантомного click после touch
    toggleDistrict(el);
  });
  // hover и тултип — только на устройствах с мышью
  if (window.matchMedia('(hover: hover)').matches) {
    el.addEventListener('mouseenter', function(e) {
      if (_dragging) return;
      if (hovered && hovered !== el) hovered.classList.remove('hover');
      hovered = el; el.classList.add('hover');
      showTip(el.dataset.name, e.clientX + 14, e.clientY - 10);
    });
    el.addEventListener('mousemove', function(e) {
      if (_dragging) { hideTip(0); return; }
      _tip.style.left = (e.clientX + 14) + 'px';
      _tip.style.top  = (e.clientY - 10) + 'px';
    });
    el.addEventListener('mouseleave', function() {
      el.classList.remove('hover'); hovered = null;
    });
  }
});
  if (window.matchMedia('(hover: hover)').matches) {
    svg.addEventListener('mouseleave', function() { hideTip(0); });
  }
} // end initMapDistricts
function tryAltExt(img) {
  if (img._tried) {
    img.style.display = 'none';
    const np = img.parentNode && img.parentNode.querySelector('.no-plan');
    if (np) np.style.display = 'flex';
    return;
  }
  img._tried = true;
  const src = img.src;
  if (/\.png$/i.test(src)) img.src = src.replace(/\.png$/i, '.jpg');
  else img.src = src.replace(/\.jpg$/i, '.png');
}
function openSortPopup() {
  document.getElementById('sort-popup-overlay').classList.add('active');
  document.getElementById('sort-popup').classList.add('active');
  var active = (typeof currentSort !== 'undefined' ? currentSort : null) || window._pendingSort || 'price-asc';
  document.querySelectorAll('.sort-popup-item').forEach(item => {
    item.classList.toggle('active', item.dataset.sort === active);
  });
}
function closeSortPopup() {
  document.getElementById('sort-popup-overlay').classList.remove('active');
  document.getElementById('sort-popup').classList.remove('active');
}
function selectSort(val) {
  window._pendingSort = val;
  closeSortPopup();
  setTimeout(function() {
    const btn = document.querySelector('.sort-btn[data-sort="' + val + '"]');
    if (btn) btn.click();
    else {
      // sort-bar убран, обновляем напрямую через глобальную переменную
      if (typeof currentSort !== 'undefined') {
        currentSort = val;
        if (typeof filterApartments === 'function') { isFirstLoad = false; filterApartments(); }
        if (typeof updateMtbState === 'function') updateMtbState();
      }
    }
  }, 250);
}
function updateFavTrack() {
  try { localStorage.setItem('apt_likes', JSON.stringify(window._favourites||[])); } catch(e){}
  const count = window._favourites ? window._favourites.length : 0;
  const track = document.getElementById('mtb-fav-track');
  const badge = document.getElementById('mtb-fav-badge');
  if (track) track.classList.toggle('has-favs', count > 0);
  if (badge) { badge.textContent = count; badge.classList.toggle('visible', count > 0); }
}
var _popupSlides = [], _popupIdx = 0;
function openImgPopup(startIdx) {
  const popup = document.getElementById('apc-img-popup');
  const track = document.getElementById('apc-img-popup-track');
  const dotsEl = document.getElementById('apc-img-popup-dots');
  // Собираем изображения из текущих слайдов карточки
  const aptSlides = document.querySelectorAll('#apc-slides .apc-slide');
  track.innerHTML = '';
  dotsEl.innerHTML = '';
  _popupSlides = [];
  aptSlides.forEach((s, i) => {
    const img = s.querySelector('img');
    if (!img) return;
    const ps = document.createElement('div');
    ps.className = 'apc-img-popup-slide' + (s.classList.contains('render') ? ' render' : '');
    const pi = document.createElement('img');
    pi.src = img.src;
    ps.appendChild(pi);
    track.appendChild(ps);
    _popupSlides.push(ps);
    const d = document.createElement('div');
    d.className = 'apc-img-popup-dot';
    d.onclick = () => popupGoTo(i);
    dotsEl.appendChild(d);
  });
  popup.classList.add('active');
  document.body.style.overflow = 'hidden';
  // Позиционируем без анимации — отключаем transition на время начальной установки позиции
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const track = document.getElementById('apc-img-popup-track');
    if (track) track.style.transition = 'none';
    popupGoTo(startIdx);
    // Возвращаем transition после позиционирования — через один кадр
    requestAnimationFrame(() => {
      if (track) track.style.transition = '';
    });
  }));
}
function popupGoTo(idx) {
  _popupIdx = Math.max(0, Math.min(idx, _popupSlides.length - 1));
  const track = document.getElementById('apc-img-popup-track');
  const w = track.parentElement ? track.parentElement.clientWidth : 0;
  track.style.transform = w > 0 ? 'translateX(-' + (_popupIdx * w) + 'px)' : 'translateX(-' + (_popupIdx * 100) + '%)';
  document.querySelectorAll('#apc-img-popup-dots .apc-img-popup-dot').forEach((d,i) => d.classList.toggle('active', i === _popupIdx));
}
function closeImgPopup() {
  document.getElementById('apc-img-popup').classList.remove('active');
  document.body.style.overflow = '';
}
// Свайп в попапе
document.addEventListener('DOMContentLoaded', function() {
  const ps = document.getElementById('apc-img-popup-slides');
  if (!ps) return;
  let tx = 0;
  ps.addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, {passive:true});
  ps.addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - tx;
    if (Math.abs(dx) > 40) popupGoTo(_popupIdx + (dx < 0 ? 1 : -1));
  });
});
function closeAptCard() {
  var overlay = document.getElementById('apt-card-overlay');
  overlay.classList.remove('active');
  if (overlay._scrollHandler) { overlay.removeEventListener('scroll', overlay._scrollHandler); overlay._scrollHandler = null; }
  var scrollY = overlay._savedScrollY || 0;
  document.body.style.position = '';
  document.body.style.top = '';
  document.body.style.left = '';
  document.body.style.right = '';
  document.body.style.overflow = '';
  window.scrollTo(0, scrollY);
  var hdr = document.querySelector('.apc-header'); if (hdr) hdr.style.background = 'transparent';
  if (window._apcResizeHandler) { window.removeEventListener('resize', window._apcResizeHandler); window._apcResizeHandler = null; }
}
function shareApt() {
  var aptId = window._currentAptId;
  var apt = aptId && window._allApts && window._allApts.find(function(a){ return a.id === aptId; });
  var base = 'https://terrace-royaltyplace.ru/';
  var shareUrl = aptId ? base + '?apt=' + encodeURIComponent(aptId) + '&v=SHARE_VERSION_PLACEHOLDER' : window.location.href;
  var title = apt ? (apt.rd + ', ' + apt.a + '\u00a0м\u00b2 \u2014 ' + apt.ps) : 'Квартира';
  if (navigator.share) navigator.share({ title: title, url: shareUrl });
  else if (navigator.clipboard) navigator.clipboard.writeText(shareUrl).then(function(){
    var btn = document.querySelector('.apc-header-right .apc-header-btn:first-child');
    if (btn) { var orig = btn.innerHTML; btn.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" stroke="#1a1a1a" stroke-width="2" fill="none" stroke-linecap="round"/></svg>'; setTimeout(function(){ btn.innerHTML = orig; }, 1500); }
  });
}
function toggleApcHeart(btn) {
  const svg = document.getElementById('apc-heart-svg');
  const liked = btn.classList.toggle('liked');
  if (liked) { svg.style.stroke = '#e8244b'; svg.style.fill = '#e8244b'; }
  else { svg.style.stroke = '#1a1a1a'; svg.style.fill = 'none'; }
  var aptId = window._currentAptId;
  if (!aptId) return;
  var apt = window._allApts && window._allApts.find(function(a){ return a.id===aptId; });
  if (!window._favourites) window._favourites = [];
  if (liked) {
    if (window._favourites.indexOf(aptId) === -1) window._favourites.push(aptId);
  } else {
    window._favourites = window._favourites.filter(function(id){ return id !== aptId; });
  }
  // sync card button in grid
  var gridCard = document.querySelector('[data-apt-id="'+aptId+'"] .apt-heart');
  if (gridCard) gridCard.classList.toggle('liked', liked);
  updateFavTrack();
  if (window.showFavToast) window.showFavToast(liked);
  // send to Google Sheets
  if (window.sendLike) window.sendLike(aptId, apt ? apt.jk : '', liked ? 'like' : 'unlike');
  // update local counter
  if (!window._aptLikes) window._aptLikes = {};
try { var _savedCounts = localStorage.getItem('apt_likes_count'); if (_savedCounts) window._aptLikes = JSON.parse(_savedCounts); } catch(e){}
  if (!window._aptLikes[aptId]) window._aptLikes[aptId] = 0;
  window._aptLikes[aptId] += liked ? 1 : -1;
  if (window._aptLikes[aptId] < 0) window._aptLikes[aptId] = 0;
  try { localStorage.setItem('apt_likes_count', JSON.stringify(window._aptLikes)); } catch(e){}
  var likesEl = document.getElementById('apc-likes-count');
  if (likesEl) likesEl.textContent = window._aptLikes[aptId];
}
function openAptCard(apt) {
  // Запускаем анимацию аватара после открытия карточки
  setTimeout(window._initAvatarAnim, 400);
  const slidesEl  = document.getElementById('apc-slides');
  const galleryEl = document.getElementById('apc-gallery');
  const inlineDots = document.getElementById('apc-inline-dots');
  const planArea   = document.getElementById('apc-plan-area');
  slidesEl.innerHTML = '';
  galleryEl.innerHTML = '';

  const allImgs = [];
  if (apt.img) allImgs.push({src: apt.img, isRender: false});
  if (apt.renders && apt.renders_count > 0) {
    for (let n = 1; n <= apt.renders_count; n++)
      allImgs.push({src: apt.renders + '/' + String(n).padStart(3,'0') + '.webp', thumbSrc: (apt.renders_thumb || apt.renders) + '/' + String(n).padStart(3,'0') + '.webp', isRender: true});
  }

  const slides = [];   // {slideEl, thumbEl}
  let activeIdx = 0;

  function goTo(idx) {
    activeIdx = Math.max(0, Math.min(idx, slides.length - 1));
    // Берём ширину контейнера слайдов — работает и локально и в Тильде
    const w = slidesEl.parentElement ? slidesEl.parentElement.clientWidth : 0;
    slidesEl.style.transform = w > 0 ? 'translateX(-' + (activeIdx * w) + 'px)' : 'translateX(-' + (activeIdx * 100) + '%)';
    slides.forEach((s, i) => s.thumbEl.classList.toggle('active', i === activeIdx));
    const activeThumb = slides[activeIdx] && slides[activeIdx].thumbEl;
    if (activeThumb) {
      const gl = galleryEl;
      const tLeft = activeThumb.offsetLeft;
      const tRight = tLeft + activeThumb.offsetWidth;
      if (tRight > gl.scrollLeft + gl.offsetWidth) gl.scrollLeft = tRight - gl.offsetWidth + 8;
      else if (tLeft < gl.scrollLeft) gl.scrollLeft = tLeft - 8;
    }
    document.querySelectorAll('#apc-inline-dots .apc-inline-dot').forEach((d,i) => d.classList.toggle('active', i === activeIdx));
    // Update header background based on slide type
    var hdr = document.querySelector('.apc-header');
    var dotsEl = document.getElementById('apc-inline-dots');
    if (hdr) {
      var curSlide = slides[activeIdx];
      var isRender = curSlide && curSlide.slideEl && curSlide.slideEl.classList.contains('render');
      var targetBg = isRender ? 'transparent' : '#f8f8f8'; setTimeout(function(){ hdr.style.background = targetBg; }, 50);
      if (dotsEl) dotsEl.classList.toggle('white', isRender);
    }
  }

  function updateInlineDots() {
    inlineDots.innerHTML = '';
    slides.forEach((_, i) => {
      const d = document.createElement('div');
      d.className = 'apc-inline-dot' + (i === activeIdx ? ' active' : '');
      inlineDots.appendChild(d);
    });
  }

  let touchX = 0, touchY = 0;
  planArea.ontouchstart = e => {
    touchX = e.touches[0].clientX;
    touchY = e.touches[0].clientY;
  };
  planArea.addEventListener('touchmove', e => {
    const dx = Math.abs(e.touches[0].clientX - touchX);
    const dy = Math.abs(e.touches[0].clientY - touchY);
    if (dx > dy) e.preventDefault();
  }, {passive: false});
  planArea.ontouchend = e => {
    const dx = e.changedTouches[0].clientX - touchX;
    const dy = e.changedTouches[0].clientY - touchY;
    if (Math.abs(dx) > 40) {
      goTo(activeIdx + (dx < 0 ? 1 : -1));
    } else if (Math.abs(dx) < 8 && Math.abs(dy) < 8) {
      // Tap — открываем fullscreen
      e.preventDefault(); // блокируем синтетический click который браузер генерирует после touch
      openImgPopup(activeIdx);
    }
  };
  // click — только для десктопа (на мобильном используется touchend + e.preventDefault)
  planArea.addEventListener('click', e => {
    if (e.sourceCapabilities && !e.sourceCapabilities.firesTouchEvents) {
      if (!e.target.closest('.apt-heart')) openImgPopup(activeIdx);
    } else if (!('ontouchstart' in window)) {
      // Десктоп без touch
      if (!e.target.closest('.apt-heart')) openImgPopup(activeIdx);
    }
  });
  requestAnimationFrame(() => requestAnimationFrame(() => { goTo(0); updateInlineDots(); }));

  function addSlide(src, isRender, insertIdx) {
    // Слайд
    const slide = document.createElement('div');
    slide.className = 'apc-slide' + (isRender ? ' render' : '');
    const sImg = document.createElement('img');
    sImg.src = src;
    slide.appendChild(sImg);
    // Thumb
    const thumb = document.createElement('div');
    thumb.className = 'apc-gallery-thumb' + (isRender ? ' render' : '');
    const tImg = document.createElement('img');
    tImg.src = src;
    thumb.appendChild(tImg);
    thumb.onclick = () => goTo(slides.indexOf(slides.find(s => s.thumbEl === thumb)));

    // Вставляем на нужную позицию
    const refSlide = slidesEl.children[insertIdx];
    const refThumb = galleryEl.children[insertIdx];
    if (refSlide) slidesEl.insertBefore(slide, refSlide);
    else slidesEl.appendChild(slide);
    if (refThumb) galleryEl.insertBefore(thumb, refThumb);
    else galleryEl.appendChild(thumb);

    slides.splice(insertIdx, 0, {slideEl: slide, thumbEl: thumb});
    goTo(activeIdx); // обновить active классы
  }

  // Создаём все слайды синхронно — порядок фиксирован
  allImgs.forEach((item, i) => {
    const slide = document.createElement('div');
    slide.className = 'apc-slide' + (item.isRender ? ' render' : '');
    slidesEl.appendChild(slide);
    const thumb = document.createElement('div');
    thumb.className = 'apc-gallery-thumb' + (item.isRender ? ' render' : '');
    thumb.onclick = () => goTo(i);
    galleryEl.appendChild(thumb);
    slides.push({slideEl: slide, thumbEl: thumb});

    // Сразу вставляем img — он загрузится сам
    const si = document.createElement('img'); si.src = item.src; slide.appendChild(si);
    const ti = document.createElement('img'); ti.src = item.thumbSrc || item.src; thumb.appendChild(ti);

    si.onerror = () => {
      if (!item.isRender) {
        const alt = item.src.replace(/\.png$/i, '.jpg');
        const altThumb = (item.thumbSrc || item.src).replace(/\.png$/i, '.jpg');
        if (si.src !== alt) { si.src = alt; ti.src = altThumb; return; }
        slide.innerHTML = '<div class="apc-plan-placeholder">Нет планировки</div>';
        thumb.innerHTML = '';
      } else {
        // Удаляем недоступный рендер из DOM и из массива
        const idx = slides.findIndex(s => s.slideEl === slide);
        if (idx !== -1) slides.splice(idx, 1);
        slide.remove();
        thumb.remove();
        // Если текущий активный сдвинулся — исправляем
        if (activeIdx >= slides.length) activeIdx = Math.max(0, slides.length - 1);
        goTo(activeIdx);
      }
    };
  });

  if (allImgs.length === 0) {
    const slide = document.createElement('div');
    slide.className = 'apc-slide';
    slide.innerHTML = '<div class="apc-plan-placeholder">Нет планировки</div>';
    slidesEl.appendChild(slide);
    slides.push({slideEl: slide, thumbEl: document.createElement('div')});
  }

  goTo(0);
  // Скидка
  const hasDiscount = apt.disc > 0 && apt.pb > 0;
  const discountPct = apt.disc || 0;
  const badgeRow = document.getElementById('apc-badge-row');
  badgeRow.innerHTML = hasDiscount ? '<span class="apc-discount-badge">-' + discountPct + '%</span>' : '';
  // Поля
  document.getElementById('apc-format').textContent = apt.rd || '—';
  document.getElementById('apc-area').textContent = apt.a ? apt.a + ' м²' : '—';
  document.getElementById('apc-kitchen').textContent = apt.k ? apt.k + ' м²' : '—';
  document.getElementById('apc-floor').textContent = apt.f || '—';
  // Срок сдачи из данных
  document.getElementById('apc-deadline').textContent = apt.deadline || '—';
  document.getElementById('apc-finish').textContent = apt.finish || '—';
  document.getElementById('apc-district').textContent = apt.district || '—';
  var viewRow = document.getElementById('apc-view-row');
  if (apt.view && apt.view.trim()) {
    document.getElementById('apc-view').textContent = apt.view;
    viewRow.style.display = '';
  } else {
    viewRow.style.display = 'none';
  }
  // Цена
  const priceEl = document.getElementById('apc-price');
  if (apt.onreq) {
    priceEl.innerHTML = `<span class="apc-onreq-badge" onclick="_onReqTip(this)">`
      + `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`
      + `Под запрос`
      + `<div class="apc-onreq-tooltip">Квартира может быть выведена в продажу застройщиком по запросу. Цена может измениться.</div>`
      + `</span>`;
  } else {
    priceEl.textContent = apt.ps || '—';
  }
  // Бейдж брони — показываем рядом со старой ценой
  const oldPriceEl = document.getElementById('apc-old-price');
  oldPriceEl.textContent = hasDiscount ? apt.pbs : '';
  const bookedEl = document.getElementById('apc-booked-label');
  if (bookedEl) bookedEl.style.display = apt.booked ? 'inline-flex' : 'none';
  // Об объекте
  const aboutBlock = document.getElementById('apc-about-block');
  if (aboutBlock) {
    let ahtml = '';
    if (apt.jk_about && apt.jk_about.length > 0) {
      ahtml += '<div class="apc-finance-divider"></div>';
      ahtml += '<div class="apc-finance-section">';
      ahtml += '<div class="apc-finance-title">Об объекте</div>';
      ahtml += '<div class="apc-about-wrap">';
      ahtml += '<div class="apc-about-text" id="apc-about-text">' + apt.jk_about.replace(/\n/g,'<br>') + '</div>';
      ahtml += '<div class="apc-about-fade" id="apc-about-fade"></div>';
      ahtml += '</div>';
      ahtml += '<div class="apc-about-more" id="apc-about-more" onclick="var t=document.getElementById(\'apc-about-text\');var f=document.getElementById(\'apc-about-fade\');t.classList.toggle(\'expanded\');f.classList.toggle(\'hidden\');this.textContent=t.classList.contains(\'expanded\')?\' Свернуть\':\'Читать полностью\'">Читать полностью</div>';
      if (apt.jk_features && apt.jk_features.length > 0) {
        ahtml += '<div class="apc-features-scroll">';
        apt.jk_features.forEach(function(f) {
          ahtml += '<div class="apc-feature-card">';
          if (f.img) ahtml += '<img src="' + f.img + '" alt="">';
          ahtml += '<div class="apc-feature-card-text">' + f.text + '</div>';
          ahtml += '</div>';
        });
        ahtml += '</div>';
      }
      ahtml += '</div>';
    }
    aboutBlock.innerHTML = ahtml;
  }

  // Акции и скидки
  const promoBlock = document.getElementById('apc-promo-block');
  if (promoBlock) {
    let phtml = '';
    if (apt.jk_promo && apt.jk_promo.length > 0) {
      // --- Каждая акция — отдельная карточка ---
      var compacted = [];
      apt.jk_promo.forEach(function(p){
        var n = String(p.name||'').trim();
        if (!n) return;
        var label = n.length > 35 ? n.slice(0, 33) + '…' : n;
        var val = '';
        if (p.value && String(p.value).toLowerCase() !== 'null' && String(p.value).trim()) {
          val = String(p.value).trim();
        }
        // Структурированные поля — порядок как в Тренде
        var fields = [];
        if (p.description && String(p.description).trim()) fields.push({label:'Описание', value:String(p.description).trim()});
        if (p.summation && String(p.summation).trim()) fields.push({label:'Суммирование с другими акциями', value:String(p.summation).trim()});
        if (p.mortgage_combinations && String(p.mortgage_combinations).trim()) fields.push({label:'Сочетание с ипотеками', value:String(p.mortgage_combinations).trim()});
        if (p.installment_combinations && String(p.installment_combinations).trim()) fields.push({label:'Сочетание с рассрочками', value:String(p.installment_combinations).trim()});
        if (p.required_documents && String(p.required_documents).trim()) fields.push({label:'Какие нужны документы', value:String(p.required_documents).trim()});
        if (fields.length === 0 && val) fields.push({label:'Значение', value:val});
        var sub = '';
        if (p.conditions && String(p.conditions).trim()) sub = String(p.conditions).trim();
        var duration = '';
        if (p.duration && String(p.duration).trim()) duration = String(p.duration).trim();
        compacted.push({label: label, val: val, fields: fields, sub: sub, duration: duration});
      });
      // 3. Сортировка: скидки → подарки → рассрочки → остальное
      compacted.sort(function(a,b){
        function pri(l){
          if (/скидк/i.test(l)) return 0;
          if (/подарок|в подарок|бесплатн/i.test(l)) return 1;
          if (/рассрочк|ипотек|взнос|ставк/i.test(l)) return 2;
          return 3;
        }
        return pri(a.label) - pri(b.label);
      });
      var packed = compacted;
      // 4. Рендер — вертикальные карточки акций (макс 4 видимых, остальные под спойлер)
      var _promoMax = 4;
      if (packed.length > 0) {
        phtml += '<div class="apc-finance-divider"></div>';
        phtml += '<div class="apc-finance-section">';
        phtml += '<div class="apc-finance-title">Акции и скидки от застройщика</div>';
        phtml += '<div class="apc-promo-list">';
        packed.forEach(function(c, idx){
          var hasDetails = c.fields && c.fields.length > 0;
          var extraClass = idx >= _promoMax ? ' apc-promo-extra' : '';
          phtml += '<div class="apc-promo-card' + extraClass + '"';
          if (hasDetails) phtml += ' onclick="_togPromoCard(this)"';
          phtml += '>';
          phtml += '<div class="apc-promo-card-top">';
          phtml += '<div class="apc-promo-card-head">';
          phtml += '<div>';
          phtml += '<span class="apc-promo-card-name">' + c.label + '</span>';
          if (c.val) phtml += '<span class="apc-promo-card-val">' + c.val + '</span>';
          phtml += '</div>';
          if (hasDetails) {
            phtml += '<svg class="apc-promo-card-chevron" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#8E8E93" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9,6 15,12 9,18"/></svg>';
          }
          phtml += '</div>';
          if (c.sub) phtml += '<div class="apc-promo-card-sub">' + c.sub + '</div>';
          phtml += '</div>';
          if (hasDetails) {
            phtml += '<div class="apc-promo-card-drawer"><div class="apc-promo-card-drawer-inner"><div class="apc-promo-card-body">';
            c.fields.forEach(function(f){
              phtml += '<div class="apc-promo-card-field">';
              phtml += '<div class="apc-promo-card-field-label">' + f.label + '</div>';
              phtml += '<div class="apc-promo-card-field-value">' + f.value + '</div>';
              phtml += '</div>';
            });
            phtml += '</div></div></div>';
          }
          phtml += '</div>';
        });
        phtml += '</div>';
        if (packed.length > _promoMax) {
          var _rest = packed.length - _promoMax;
          var _pw = _rest === 1 ? 'акция' : (_rest < 5 ? 'акции' : 'акций');
          phtml += '<div class="apc-promo-more" onclick="_togPromoMore(this)">Ещё ' + _rest + ' ' + _pw + '</div>';
        }
        phtml += '</div>';
      }
    }
    promoBlock.innerHTML = phtml;
  }

  // Hoff бейдж
  const hoffWrap = document.getElementById('apc-hoff-wrap');
  const hoffTooltip = document.getElementById('apc-hoff-tooltip');
  if (hoffWrap) {
    hoffWrap.style.display = apt.hoff ? 'inline-flex' : 'none';
  }

  // Рассрочки
  // ── Рассрочки ─────────────────────────────────────
  const instBlock = document.getElementById('apc-inst-block');
  if (instBlock) {
    let ihtml = '';
    const inst = apt.installments || [];
    function _val(v) { if (!v && v !== 0) return null; var s = String(v).trim().toLowerCase(); if (!s || s === 'null' || s === 'none' || s === 'undefined' || s.startsWith('null') || s.endsWith('null')) return null; return v; }

    if (inst.length > 0) {
      ihtml += '<div class="apc-finance-divider"></div>';
      ihtml += '<div class="apc-finance-section">';
      ihtml += '<div class="apc-finance-title">Доступные варианты рассрочек</div>';
      var instShowCount = 4;
      ihtml += '<div class="apc-promo-list">';
      inst.forEach(function(r, idx) {
        var pv   = _val(r.pv || r.firstpay);
        var term = _val(r.srok || r.term);
        var price = r.price || '';
        var hidden = idx >= instShowCount ? ' apc-promo-hidden' : '';
        var cardId = 'apc-inst-card-' + idx;

        var tagsHtml = '';
        var hasPvTag = false;
        if (r.tags && r.tags.length) {
          r.tags.forEach(function(t){
            var isPv = /ПВ|первонач/i.test(String(t));
            if (isPv) hasPvTag = true;
            var cls = isPv ? 'apc-inst-tag apc-inst-tag-pv' : 'apc-inst-tag';
            tagsHtml += '<span class="' + cls + '">' + t + '</span>';
          });
        }

        ihtml += '<div class="apc-inst-card' + hidden + '" id="' + cardId + '" onclick="_togInst(\'' + cardId + '\')">';
        ihtml += '<div class="apc-inst-top">';
        ihtml += '<div class="apc-inst-head">';
        ihtml += '<span class="apc-inst-name">' + r.name + '</span>';
        ihtml += '<svg class="apc-inst-chevron" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#8E8E93" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9,6 15,12 9,18"/></svg>';
        ihtml += '</div>';

        // Первоначальный взнос — зелёная пилюля (если ещё не упомянут в тегах)
        var hasPvTag = r.tags && r.tags.some(function(t){ return /ПВ|первонач/i.test(String(t)); });
        if (!hasPvTag) {
          var pvPct = null;
          if (r.payment_schedule && r.payment_schedule.length) {
            var m = r.payment_schedule[0].match(/(\d+)\s*%/);
            if (m) pvPct = parseInt(m[1]);
          }
          if (pvPct === null) {
            var nm = r.name.match(/(\d+)/);
            if (nm) pvPct = parseInt(nm[1]);
          }
          if (pvPct !== null) {
            tagsHtml = '<span class="apc-inst-tag apc-inst-tag-pv">ПВ ' + pvPct + '%</span>' + tagsHtml;
          }
        }

        if (tagsHtml) ihtml += '<div class="apc-inst-tags">' + tagsHtml + '</div>';
        ihtml += '</div>'; // top

        // Drawer
        ihtml += '<div class="apc-inst-drawer"><div class="apc-inst-drawer-inner"><div class="apc-inst-body">';

        var tableRows = [
          ['Переход на ипотеку', r.transition_to_mortgage],
          ['Мат. капитал', r.maternal_capital],
          ['Страхование', r.comprehensive_insurance],
          ['Ключи до оплаты', r.keys_before_full_payment],
        ].filter(function(row){ return row[1]; });
        if (tableRows.length) {
          tableRows.forEach(function(row){
            ihtml += '<div class="apc-inst-grid-row"><span class="apc-inst-grid-lbl">' + row[0] + '</span><span class="apc-inst-grid-val">' + row[1] + '</span></div>';
          });
        }

        if (r.payment_schedule && r.payment_schedule.length) {
          ihtml += '<div class="apc-inst-sched-title">График платежей</div>';
          ihtml += '<div class="apc-inst-sched">';
          r.payment_schedule.forEach(function(item){
            ihtml += '<div class="apc-inst-sched-item"><span class="apc-inst-check">✓</span>' + item + '</div>';
          });
          ihtml += '</div>';
        }

        if (r.comment && r.comment.length) {
          ihtml += '<div class="apc-inst-comment-title">Комментарий</div>';
          ihtml += '<div class="apc-inst-sched">';
          r.comment.forEach(function(item){
            ihtml += '<div class="apc-inst-sched-item"><span class="apc-inst-check">✓</span>' + item + '</div>';
          });
          ihtml += '</div>';
        }

        ihtml += '</div></div></div>'; // body + inner + drawer
        ihtml += '</div>'; // card
      });
      ihtml += '</div>';
      if (inst.length > instShowCount) {
        var restInst = inst.length - instShowCount;
        var instWord = _dp(restInst,'программа','программы','программ');
        ihtml += '<div class="apc-promo-more" onclick="_togInstMore(this)">Ещё ' + restInst + ' ' + instWord + '</div>';
      }
      ihtml += '</div>';
    }
    instBlock.innerHTML = ihtml;
  }

  // ── Ипотека ──────────────────────────────────────
  const mortBlock = document.getElementById('apc-mort-block');
  if (mortBlock) {
    let mhtml = '';
    let mort = apt.mortgage || [];
    const inst = apt.installments || [];
    function _mval(v) { if (!v && v !== 0) return null; var s = String(v).trim().toLowerCase(); if (!s || s === 'null' || s === 'none' || s === 'undefined' || s.startsWith('null') || s.endsWith('null')) return null; return v; }
    function _mnum(v) { var s = String(v == null ? '' : v).replace('%','').replace(',','.').trim(); var n = parseFloat(s); return isNaN(n) ? null : n; }
    function _mclean(v) { return String(v == null ? '' : v).replace(/^от\s*/i,'').trim(); }

    var mortFiltered = mort.filter(function(m) { return !!_mval(m.rate); });

    if (mortFiltered.length > 0) {
      mhtml += '<div class="apc-finance-divider"></div>';
      mhtml += '<div class="apc-finance-section">';
      mhtml += '<div class="apc-finance-title">Ипотека</div>';
      var mortShowCount = 4;
      mhtml += '<div class="apc-mtg-list">';

      mortFiltered.forEach(function(m, idx) {
        var hidden = idx >= mortShowCount ? ' apc-promo-hidden' : '';
        var rowId = 'apc-mtg-row-' + idx;
        var rateNum  = _mnum(m.rate);
        var pvVal    = _mval(m.pv);
        var periodVal = _mval(m.period);
        var isLow = rateNum !== null && rateNum < 12;

        // ── строка ──
        mhtml += '<div class="apc-mtg-row' + (isLow ? ' apc-mtg-low' : '') + hidden + '" id="' + rowId + '" onclick="_togMtg(\'' + rowId + '\')">';
        mhtml += '<div class="apc-mtg-head">';
        mhtml += '<div class="apc-mtg-info"><div class="apc-mtg-name">' + m.prog + '</div>';
        var subParts = [];
        if (pvVal) subParts.push('ПВ ' + _mclean(pvVal));
        if (periodVal) subParts.push('до ' + periodVal + ' лет');
        if (subParts.length) mhtml += '<div class="apc-mtg-sub">' + subParts.join(' · ') + '</div>';
        mhtml += '</div>';
        mhtml += '<div class="apc-mtg-rate"><span class="apc-mtg-rate-num">' + (rateNum !== null ? rateNum : _mclean(m.rate)) + '</span><span class="apc-mtg-rate-pct">%</span></div>';
        mhtml += '</div>'; // head

        // ── раскрывающаяся панель ──
        mhtml += '<div class="apc-mtg-panel"><div class="apc-mtg-panel-inner"><div class="apc-mtg-detail">';

        var hasTimeline = (m.first_rate !== null && m.first_rate !== undefined && m.first_months && m.second_rate);
        if (hasTimeline) {
          mhtml += '<div class="apc-mtg-timeline">';
          mhtml += '<div class="apc-mtg-tl-item"><div class="apc-mtg-tl-dot"></div><div class="apc-mtg-tl-period">первые ' + m.first_months + ' мес.</div><div class="apc-mtg-tl-rate">' + m.first_rate + '%</div></div>';
          mhtml += '<div class="apc-mtg-tl-item"><div class="apc-mtg-tl-dot gray"></div><div class="apc-mtg-tl-period">с ' + (m.first_months + 1) + ' месяца</div><div class="apc-mtg-tl-rate">' + m.second_rate + '%</div></div>';
          mhtml += '</div>';
        } else if (_mval(m.rate_note)) {
          mhtml += '<div class="apc-mtg-note">' + m.rate_note + '</div>';
        }

        // чипы
        var chips = [];
        if (pvVal) chips.push('ПВ <b>' + _mclean(pvVal) + '</b>');
        if (periodVal) chips.push('срок <b>до ' + periodVal + ' лет</b>');
        if (chips.length) {
          mhtml += '<div class="apc-mtg-chips">';
          chips.forEach(function(c){ mhtml += '<span class="apc-mtg-chip">' + c + '</span>'; });
          mhtml += '</div>';
        }

        // Налоговый вычет (фиксированный по НК РФ, одинаков для всех программ)
        mhtml += '<div class="apc-mtg-deduction">';
        mhtml += '<div class="apc-mtg-ded-head"><span class="apc-mtg-ded-ic">↩</span>Налоговый вычет <b>до 650 000 ₽</b></div>';
        mhtml += '<div class="apc-mtg-ded-rows">';
        mhtml += '<div class="apc-mtg-ded-row"><span>за квартиру</span><span>260 000 ₽</span></div>';
        mhtml += '<div class="apc-mtg-ded-row"><span>за проценты по кредиту</span><span>390 000 ₽</span></div>';
        mhtml += '</div></div>';

        mhtml += '</div></div></div>'; // detail + inner + panel
        mhtml += '</div>'; // row
      });

      mhtml += '</div>'; // list
      if (mortFiltered.length > mortShowCount) {
        var restMort = mortFiltered.length - mortShowCount;
        var mortWord = _dp(restMort,'программа','программы','программ');
        mhtml += '<div class="apc-promo-more" onclick="_togMtgMore(this)">Ещё ' + restMort + ' ' + mortWord + '</div>';
      }
      mhtml += '</div>'; // section
    }
    mort = mortFiltered;

    if (inst.length > 0 || mort.length > 0) {
      mhtml += '<div class="apc-finance-disclaimer">* Условия программ актуальны на дату обновления и носят ознакомительный характер. Уточняйте у менеджера.</div>';
    }

    mortBlock.innerHTML = mhtml;
  }


  // ── Похожие варианты ────────────────────────────────────────────
  var simBlock = document.getElementById('apc-similar-block');
  if (simBlock) {
    function scoreSimilar(a, allowSameJk) {
      if (a.id === apt.id) return -1;
      if (!allowSameJk && a.jk === apt.jk) return -1;
      if (!a.p || !apt.p) return -1;
      var score = 0;
      var priceDiff = Math.abs(a.p - apt.p) / apt.p;
      var maxPct = Math.min(0.40, 500000000 / apt.p);
      if (priceDiff > maxPct) return -1;
      if (priceDiff <= maxPct * 0.5) score += 3;
      else if (priceDiff <= maxPct * 0.8) score += 1;
      if (a.r === apt.r) score += 2;
      if (a.district && apt.district && a.district === apt.district) score += 3;
      if (a.a && apt.a && Math.abs(a.a - apt.a) / apt.a <= 0.15) score += 2;
      if (a.deadline && apt.deadline && a.deadline === apt.deadline) score += 1;
      if (a.finish && apt.finish && a.finish === apt.finish) score += 1;
      return score;
    }
    function getSimilar(allowSameJk) {
      var seen = {}; var res = [];
      apartmentsData.map(function(a) {
        return { apt: a, score: scoreSimilar(a, allowSameJk) };
      }).filter(function(x) { return x.score >= 0; })
      .sort(function(x, y) { return y.score - x.score; })
      .forEach(function(x) {
        var jk = x.apt.jk || x.apt.id;
        if (!seen[jk]) { seen[jk] = true; res.push(x.apt); }
      });
      return res.slice(0, 8);
    }
    var simApts = getSimilar(false);
    if (simApts.length < 6) simApts = getSimilar(true);

    if (simApts.length > 0) {
      var sh = '<div class="apc-finance-divider"></div>';
      sh += '<div class="apc-similar-section">';
      sh += '<div class="apc-similar-title">Похожие варианты</div>';
      sh += '<div class="apc-similar-scroll">';
      simApts.forEach(function(s) {
        var hasBadge = s.disc > 0 && s.pb > 0;
        var escapedId = s.id.replace(/'/g, "\\'");
        sh += '<div class="apc-similar-card" onclick="(function(){var a=window._allApts&&window._allApts.find(function(x){return x.id===\''+escapedId+'\';});if(a)openAptCard(a);})()">';
        sh += '<div class="apc-similar-img">';
        if (s.img) sh += '<img src="' + s.img + '" loading="lazy" onerror="this.style.display=\'none\'">';
        else sh += '<div style="color:#ccc;font-size:11px">Нет фото</div>';
        sh += '</div>';
        sh += '<div style="display:flex;align-items:center;gap:0;margin-bottom:2px">';
        sh += '<div class="apc-similar-price">' + s.ps + '</div>';
        if (hasBadge) sh += '<div class="apc-similar-badge">-' + s.disc + '%</div>';
        sh += '</div>';
        sh += '<div class="apc-similar-meta">' + s.rd + ', ' + s.a + '\u00a0м²</div>';
        if (s.district) sh += '<div class="apc-similar-meta">' + s.district + '</div>';
        sh += '</div>';
      });
      sh += '</div></div>';
      simBlock.innerHTML = sh;
    } else {
      simBlock.innerHTML = '';
    }
  }


  var realCount = (window._aptLikes && window._aptLikes[apt.id]) || 0;
  document.getElementById('apc-likes-count').textContent = realCount;
  // Сброс сердечка
  const likesBtn = document.getElementById('apc-likes-btn');
  const svg = document.getElementById('apc-heart-svg');
  var alreadyLiked = (window._favourites||[]).indexOf(apt.id) !== -1;
  likesBtn.classList.toggle('liked', alreadyLiked);
  svg.style.stroke = alreadyLiked ? '#e8244b' : '#1a1a1a';
  svg.style.fill = alreadyLiked ? '#e8244b' : 'none';
  // Открываем
  window._currentAptId = apt.id;
  const overlay = document.getElementById('apt-card-overlay');
  document.body.appendChild(overlay);
  overlay.style.height = window.innerHeight + 'px';
  window._apcResizeHandler = function(){ overlay.style.height = window.innerHeight + 'px'; };
  window.addEventListener('resize', window._apcResizeHandler);
  overlay.scrollTop = 0;
  overlay.classList.add('active');
  var _scrollY = window.scrollY || window.pageYOffset || 0;
  overlay._savedScrollY = _scrollY;
  document.body.style.position = 'fixed';
  document.body.style.top = '-' + _scrollY + 'px';
  document.body.style.left = '0';
  document.body.style.right = '0';
  document.body.style.overflow = 'hidden';
  var hdrEl = document.querySelector('.apc-header'); if (hdrEl) hdrEl.style.background = '#f8f8f8';
  overlay._scrollHandler = function() {
    var st = overlay.scrollTop;
    var hdr = document.querySelector('.apc-header');
    if (!hdr) return;
    var planArea = document.getElementById('apc-plan-area');
    var threshold = planArea ? planArea.offsetHeight : window.innerHeight * 0.6;
    var fade = Math.max(0, Math.min(1, (st - threshold + 60) / 60));
    var alpha = Math.round(fade * 248);
    hdr.style.background = 'rgba(' + alpha + ',' + alpha + ',' + alpha + ',' + fade + ')' ;
  };
  overlay.addEventListener('scroll', overlay._scrollHandler);

  /* ════════════════ ROYALTY ENHANCE — все правки попапа ════════════════ */
  try {
    var _RE_overlay = document.getElementById('apt-card-overlay');
    var _RE_apcBody = _RE_overlay && _RE_overlay.querySelector('.apc-body');
    if (_RE_overlay && _RE_apcBody) {

      // 0. Idempotent: снять прошлые обёртки на случай повторного вызова
      var _old = document.getElementById('apc-top-island');
      if (_old) { while (_old.firstChild) _old.parentNode.insertBefore(_old.firstChild, _old); _old.remove(); }
      Array.prototype.slice.call(document.querySelectorAll('[data-island="1"]')).forEach(function(el){
        while (el.firstChild) el.parentNode.insertBefore(el.firstChild, el);
        el.remove();
      });
      // Удалить «сироты» рассрочек/ипотеки, вытащенные step 12
      var _instBlock = document.getElementById('apc-inst-block');
      var _mortBlock = document.getElementById('apc-mort-block');
      var _aboutBlock = document.getElementById('apc-about-block');
      var _promoBlock = document.getElementById('apc-promo-block');
      Array.prototype.slice.call(document.querySelectorAll('.apc-finance-section')).forEach(function(el){
        if (_instBlock && _instBlock.contains(el)) return;
        if (_mortBlock && _mortBlock.contains(el)) return;
        if (_aboutBlock && _aboutBlock.contains(el)) return;
        if (_promoBlock && _promoBlock.contains(el)) return;
        el.remove();
      });
      Array.prototype.slice.call(document.querySelectorAll('.apc-finance-disclaimer')).forEach(function(el){
        if (_instBlock && _instBlock.contains(el)) return;
        if (_mortBlock && _mortBlock.contains(el)) return;
        el.remove();
      });
      // Снять обёртки price-line, old-price-wrap, badge-inline
      var _plOld = document.getElementById('apc-price-line');
      if (_plOld) { while (_plOld.firstChild) _plOld.parentNode.insertBefore(_plOld.firstChild, _plOld); _plOld.remove(); }
      var _blOld = document.getElementById('apc-badges-line');
      if (_blOld) { while (_blOld.firstChild) _blOld.parentNode.insertBefore(_blOld.firstChild, _blOld); _blOld.remove(); }
      var _owOld = document.getElementById('apc-old-price-wrap');
      if (_owOld) { while (_owOld.firstChild) _owOld.parentNode.insertBefore(_owOld.firstChild, _owOld); _owOld.remove(); }
      var _biOld = document.getElementById('apc-badge-inline');
      if (_biOld) _biOld.remove();
      var _vbOld = document.getElementById('apc-view-banner');
      if (_vbOld) _vbOld.remove();
      var _sgOld = document.getElementById('apc-spec-grid');
      if (_sgOld) _sgOld.remove();
      // Снять класс стилизации цены и восстановить видимость строк
      Array.prototype.slice.call(document.querySelectorAll('.apc-price-main-styled')).forEach(function(el){ el.classList.remove('apc-price-main-styled'); });
      Array.prototype.slice.call(document.querySelectorAll('.apc-row')).forEach(function(r){ r.style.display = ''; });

      // 1. Собрать данные паспорта
      var _rows = Array.prototype.slice.call(document.querySelectorAll('.apc-row'));
      var _data = {};
      _rows.forEach(function(row){
        var c = row.children;
        if (c.length >= 2) {
          var l = (c[0].textContent||'').trim();
          var v = (c[c.length-1].textContent||'').trim();
          _data[l] = v;
        }
      });

      // 2. Скрыть дубли (Формат/Площадь/Район — они в подзаголовке) и пустые строки
      var _hideDup = ['Формат','Площадь','Район'];
      _rows.forEach(function(row){
        // Всегда скрывать view-row — вид показывается пилюлей
        if (row.classList.contains('apc-view-row')) { row.style.display = 'none'; return; }
        var c = row.children;
        if (c.length >= 2) {
          var l = (c[0].textContent||'').trim();
          var v = (c[c.length-1].textContent||'').trim();
          if (_hideDup.indexOf(l) >= 0 || !v || v === '—' || v === '-') row.style.display = 'none';
        }
      });

      // 3. Перенести .apc-price-row в начало body
      var _priceRow = document.querySelector('.apc-price-row');
      if (_priceRow && _RE_apcBody.firstChild !== _priceRow) {
        _RE_apcBody.insertBefore(_priceRow, _RE_apcBody.firstChild);
      }

      // 4. Найти главную цену и старую цену
      var _priceMain = null;
      if (_priceRow) {
        var _els = _priceRow.querySelectorAll('*');
        for (var _i=0; _i<_els.length; _i++) {
          var _e = _els[_i];
          if (_e.children.length === 0 && /\d{1,3}[\s\u00A0]\d{3}[\s\u00A0]\d{3}/.test((_e.textContent||'').trim())) {
            _priceMain = _e;
            _priceMain.classList.add('apc-price-main-styled');
            break;
          }
        }
        // Fallback: «Под запрос» — переиспользовать #apc-price как цену
        if (!_priceMain) {
          var _priceSpan = document.getElementById('apc-price');
          if (_priceSpan) {
            _priceSpan.innerHTML = '';
            _priceSpan.textContent = 'Под запрос';
            _priceSpan.classList.add('apc-price-main-styled');
            _priceMain = _priceSpan;
          }
        }
      }
      var _oldPrice = _priceRow ? _priceRow.querySelector('s, del') : null;
      if (!_oldPrice && _priceRow) {
        var _aE = _priceRow.querySelectorAll('*');
        for (var _j=0; _j<_aE.length; _j++) {
          var _e2 = _aE[_j];
          if (_e2.children.length === 0 && getComputedStyle(_e2).textDecorationLine.indexOf('line-through') >= 0) {
            _oldPrice = _e2; break;
          }
        }
      }
      if (_oldPrice) _oldPrice.classList.add('apc-old-price-styled');

      // 5. Бейдж скидки — создать inline-элемент (старая цена идёт отдельной строкой в step 6)
      var _badgeRow = document.getElementById('apc-badge-row');
      var _badgeText = _badgeRow ? (_badgeRow.textContent||'').trim() : '';
      if (_badgeRow) _badgeRow.style.display = 'none';

      // Очистить старые inline-элементы
      var _oldBadgeInline = document.getElementById('apc-badge-inline');
      if (_oldBadgeInline) _oldBadgeInline.remove();
      var _oldWrap = document.getElementById('apc-old-price-wrap');
      if (_oldWrap) { while (_oldWrap.firstChild) _oldWrap.parentNode.insertBefore(_oldWrap.firstChild, _oldWrap); _oldWrap.remove(); }

      // Создать badge inline
      var _badgeInline = null;
      if (_badgeText) {
        _badgeInline = document.createElement('span');
        _badgeInline.id = 'apc-badge-inline';
        _badgeInline.textContent = _badgeText;
      }

      // 6. Главная строка цены: price + discount + badges; старая цена ниже
      var _topLine = document.getElementById('apc-price-line');
      if (_topLine) { while (_topLine.firstChild) _topLine.parentNode.insertBefore(_topLine.firstChild, _topLine); _topLine.remove(); }
      var _badgesLine = document.getElementById('apc-badges-line');
      if (_badgesLine) { while (_badgesLine.firstChild) _badgesLine.parentNode.insertBefore(_badgesLine.firstChild, _badgesLine); _badgesLine.remove(); }
      _oldWrap = document.getElementById('apc-old-price-wrap');
      if (_oldWrap) { while (_oldWrap.firstChild) _oldWrap.parentNode.insertBefore(_oldWrap.firstChild, _oldWrap); _oldWrap.remove(); }
      var _bookedLabel = document.getElementById('apc-booked-label');
      var _hoffWrap = document.getElementById('apc-hoff-wrap');
      if (_priceMain && _priceRow) {
        _topLine = document.createElement('div');
        _topLine.id = 'apc-price-line';
        _priceRow.insertBefore(_topLine, _priceRow.firstChild);
        _topLine.appendChild(_priceMain);
        if (_badgeInline) _topLine.appendChild(_badgeInline);
        if (_bookedLabel) _topLine.appendChild(_bookedLabel);
        if (_hoffWrap) _topLine.appendChild(_hoffWrap);
        // Старая цена — отдельной строкой ниже
        if (_oldPrice && (_oldPrice.textContent||'').trim()) {
          _oldPrice.style.display = 'block';
          _oldPrice.style.marginTop = '4px';
          _topLine.parentNode.insertBefore(_oldPrice, _topLine.nextSibling);
        }
      }

      // 7. Подзаголовок «N комнат · X м² · Район р-н»
      var _oldSub = document.getElementById('apc-subtitle');
      if (_oldSub) _oldSub.remove();
      var _subParts = [];
      if (_data['Формат']) _subParts.push(_data['Формат']);
      if (_data['Площадь']) _subParts.push(_data['Площадь']);
      if (_data['Район']) _subParts.push(_data['Район'] + ' р-н');
      if (_subParts.length && _priceRow) {
        var _sub = document.createElement('div');
        _sub.id = 'apc-subtitle';
        _sub.textContent = _subParts.join(' · ');
        // Вставить после старой цены (если есть), иначе после price-line
        var _insertAfter = _oldPrice && _oldPrice.parentNode === _priceRow ? _oldPrice : _topLine;
        if (_insertAfter && _insertAfter.nextSibling) _priceRow.insertBefore(_sub, _insertAfter.nextSibling);
        else _priceRow.appendChild(_sub);
      }

      // 8. Сетка характеристик с иконками (Lucide SVG из S3)
      var _specIconUrl = {
        'кухня':     'https://storage.yandexcloud.net/royaltyplace/terrace/%D0%BA%D1%83%D1%85%D0%BD%D1%8F.svg',
        'этаж':      'https://storage.yandexcloud.net/royaltyplace/terrace/%D1%8D%D1%82%D0%B0%D0%B6.svg',
        'срок сдачи':'https://storage.yandexcloud.net/royaltyplace/terrace/%D1%81%D1%80%D0%BE%D0%BA_%D1%81%D0%B4%D0%B0%D1%87%D0%B8.svg',
        'отделка':   'https://storage.yandexcloud.net/royaltyplace/terrace/%D0%BE%D1%82%D0%B4%D0%B5%D0%BB%D0%BA%D0%B0.svg'
      };
      var _oldGrid = document.getElementById('apc-spec-grid');
      if (_oldGrid) _oldGrid.remove();
      var _visRows = _rows.filter(function(r){ return r.style.display !== 'none' && !r.classList.contains('apc-view-row'); });
      var _items = _visRows.map(function(row){
        var c = row.children;
        return { label:(c[0].textContent||'').trim(), value:(c[c.length-1].textContent||'').trim(), el:row };
      }).filter(function(it){ return it.value && it.value !== '—'; });
      if (_items.length > 0) {
        var _grid = document.createElement('div');
        _grid.id = 'apc-spec-grid';
        _items.forEach(function(it){
          var cell = document.createElement('div');
          cell.className = 'apc-spec-cell';
          var inner = document.createElement('div');
          inner.className = 'apc-spec-inner';
          var _lk = it.label.toLowerCase();
          var _icoUrl = _specIconUrl[_lk] || '';
          if (_icoUrl) {
            var ico = document.createElement('div'); ico.className = 'apc-spec-icon';
            var img = document.createElement('img'); img.src = _icoUrl; img.alt = _lk; img.width = 20; img.height = 20;
            ico.appendChild(img); inner.appendChild(ico);
          }
          var v = document.createElement('div'); v.className = 'apc-spec-value'; v.textContent = it.value;
          var l = document.createElement('div'); l.className = 'apc-spec-label'; l.textContent = _lk;
          inner.appendChild(v); inner.appendChild(l); cell.appendChild(inner); _grid.appendChild(cell);
        });
        _items[0].el.parentNode.insertBefore(_grid, _items[0].el);
        _items.forEach(function(it){ it.el.style.display = 'none'; });
      }

      // 9. Бейдж «Видовая квартира» + тултип с деталями вида
      var _oldBanner = document.getElementById('apc-view-banner');
      if (_oldBanner) _oldBanner.remove();
      var _viewVal = (apt && apt.view) ? String(apt.view).trim() : '';
      if (_viewVal && _viewVal.toLowerCase() !== 'nan' && _viewVal !== '—') {
        // Форматируем текст тултипа
        var _viewTipText = _viewVal;
        if (!/^[Вв]ид\s/i.test(_viewVal)) _viewTipText = 'Вид на ' + _viewVal;
        var _banner = document.createElement('span');
        _banner.id = 'apc-view-banner';
        _banner.setAttribute('onclick', '_viewTip(this,event)');
        _banner.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg><span>Видовая</span><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><polyline points="9,6 15,12 9,18"/></svg><div class="apc-promo-tooltip">'+_viewTipText+'</div>';
        var _sub2 = document.getElementById('apc-subtitle');
        if (_sub2) {
          if (!_sub2.querySelector('.apc-sub-text')) {
            var _txt = _sub2.textContent;
            _sub2.textContent = '';
            var _sp = document.createElement('span');
            _sp.className = 'apc-sub-text';
            _sp.textContent = _txt;
            _sub2.appendChild(_sp);
          }
          _sub2.appendChild(_banner);
        }
      }

      // 10. Top-island: planArea + gallery + priceRow в одной белой карточке
      var _planArea = document.getElementById('apc-plan-area');
      var _gallery = document.getElementById('apc-gallery');
      if (_planArea && _gallery && _priceRow) {
        var _topIsland = document.createElement('div');
        _topIsland.id = 'apc-top-island';
        _topIsland.dataset.island = '1';
        _RE_overlay.insertBefore(_topIsland, _planArea);
        _topIsland.appendChild(_planArea);
        _topIsland.appendChild(_gallery);
        _topIsland.appendChild(_priceRow);
      }

      // 11. Завернуть остальные блоки apc-body в острова
      var _ch = Array.prototype.slice.call(_RE_apcBody.children);
      var _grp = null, _grps = [];
      _ch.forEach(function(child){
        if (child.style.display === 'none' || child.offsetHeight === 0) return;
        var isRowGroup = child.classList.contains('apc-row') || child.classList.contains('apc-view-row') || child.id === 'apc-spec-grid';
        if (isRowGroup) {
          if (!_grp) { _grp = {items:[]}; _grps.push(_grp); }
          _grp.items.push(child);
        } else {
          _grp = null;
          _grps.push({items:[child]});
        }
      });
      _grps.forEach(function(g){
        var f = g.items[0];
        var w = document.createElement('div');
        w.dataset.island = '1';
        f.parentNode.insertBefore(w, f);
        g.items.forEach(function(it){ w.appendChild(it); });
      });

      // 13. Sticky header center
      var _hdr = _RE_overlay.querySelector('.apc-header');
      if (_hdr) {
        var _oc = _hdr.querySelector('.apc-header-center');
        if (_oc) _oc.remove();
        var _center = document.createElement('div');
        _center.className = 'apc-header-center';
        var _pTxt = _priceMain ? _priceMain.textContent.trim() : '';
        var _sTxt = _subParts.join(' · ');
        _center.innerHTML = '<div class="hdr-price">'+_pTxt+'</div><div class="hdr-sub">'+_sTxt+'</div>';
        _hdr.appendChild(_center);

        // Заменяем старый scroll-handler на наш
        if (_RE_overlay._scrollHandler) {
          _RE_overlay.removeEventListener('scroll', _RE_overlay._scrollHandler);
        }
        _RE_overlay._scrollHandler = function(){
          var st = _RE_overlay.scrollTop;
          if (st > 320) _hdr.classList.add('scrolled');
          else _hdr.classList.remove('scrolled');
        };
        _RE_overlay.addEventListener('scroll', _RE_overlay._scrollHandler);
        _RE_overlay._scrollHandler();
      }

      // 14. Шевроны/стрелки — авто-поворот при «Свернуть»
      var _checkExp = function(){
        Array.prototype.slice.call(document.querySelectorAll('#apc-about-more, .apc-fin-more')).forEach(function(el){
          var t = (el.textContent||'').trim().toLowerCase();
          if (t.indexOf('сверну') === 0 || t.indexOf('скры') === 0) el.setAttribute('data-expanded','');
          else el.removeAttribute('data-expanded');
        });
      };
      if (window._linkExpandObserver) window._linkExpandObserver.disconnect();
      window._linkExpandObserver = new MutationObserver(_checkExp);
      Array.prototype.slice.call(document.querySelectorAll('#apc-about-more, .apc-fin-more')).forEach(function(el){
        window._linkExpandObserver.observe(el, {childList:true, subtree:true, characterData:true});
      });
      _checkExp();
    }
  } catch(_eRE) {
    if (window.console && console.warn) console.warn('royaltyEnhance failed', _eRE);
  }
  /* ════════════════ END ROYALTY ENHANCE ════════════════ */

}
function toggleHeart(btn, e) {
  e.stopPropagation();
  var card = btn.closest('[data-apt-id]');
  if (!card) return;
  var aptId = card.dataset.aptId;
  const liked = btn.classList.toggle('liked');
  btn.classList.remove('pop');
  void btn.offsetWidth;
  btn.classList.add('pop');
  btn.addEventListener('animationend', function(){ btn.classList.remove('pop'); }, {once:true});
  if (!window._favourites) window._favourites = [];
  if (liked) {
    if (window._favourites.indexOf(aptId) === -1) window._favourites.push(aptId);
  } else {
    window._favourites = window._favourites.filter(function(id){ return id !== aptId; });
  }
  updateFavTrack();
  if (window.showFavToast) window.showFavToast(liked);
}
document.addEventListener('DOMContentLoaded', function () {
['img-modal-overlay','mobile-filter-popup','mobile-filter-overlay','floating-filter-btn','desktop-filter-modal-overlay','mobile-top-bar','sort-popup-overlay','sort-popup','apt-card-overlay','apc-img-popup']
.forEach(id => { const el = document.getElementById(id); if (el) document.body.appendChild(el); });
const container = document.getElementById('flats-container');
const loadBtn   = document.getElementById('load-more-btn');
const noRes     = document.getElementById('no-results');
const roomBtns  = document.querySelectorAll('.room-btn, .m-room-btn');
const finishCbs = document.querySelectorAll('.finish-cb');
let currentRooms = ['all'], selectedFinishes = [], showCount = 8;
const step = 8;
let isSyncing = false, isFirstLoad = true;
let currentSort = 'price-asc';
window.updateMtbState = function updateMtbState() {
  const filterBtn = document.getElementById('mtb-filter-btn');
  const sortBtn = document.querySelector('#mobile-top-bar .mtb-icon-btn:nth-child(2)');
  var _sm = false;
  try {
    var _sr = window.sliderRanges;
    var _sA = window.SL[window.innerWidth>900?'d-slider-area':'m-inline-slider-area'];
    var _sP = window.SL[window.innerWidth>900?'d-slider-price':'m-inline-slider-price'];
    if (_sA && _sP && _sr) {
      var _av = _sA.noUiSlider.get().map(Number), _pv = _sP.noUiSlider.get().map(Number);
      _sm = Math.round(_av[0]) > Math.round(Number(_sr.a.min)) || Math.round(_av[1]) < Math.round(Number(_sr.a.max)) ||
            Math.round(_pv[0]) > Math.round(Number(_sr.p.min)) || Math.round(_pv[1]) < Math.round(Number(_sr.p.max));
    }
  } catch(e){}
  filterActive = !currentRooms.includes('all') || selectedFinishes.length > 0 || (window.selectedMapDistricts && window.selectedMapDistricts.length > 0) || _sm;
  const sortActive = currentSort && currentSort !== 'price-asc';
  if (filterBtn) filterBtn.classList.toggle('active', filterActive);
  if (sortBtn) sortBtn.classList.toggle('active', !!sortActive);
};
function toggleFavPanel2() { window.toggleFavPanel(); }
window.toggleFavPanel = function() {
  var panel = document.getElementById('fav-panel');
  var overlay = document.getElementById('fav-panel-overlay');
  if (!panel) return;
  var open = panel.classList.toggle('open');
  overlay.classList.toggle('open', open);
  document.body.style.overflow = open ? 'hidden' : '';
  if (open) window.renderFavPanel();
};
window.renderFavPanel = function() {
  var list = document.getElementById('fav-list');
  var countEl = document.getElementById('fav-count');
  if (!list) return;
  var favIds = window._favourites || [];
  var allApts = window._allApts || [];
  var favApts = allApts.filter(function(a){ return favIds.indexOf(a.id) !== -1; });
  var sort = window._favSort || 'district';
  favApts.sort(function(a,b){
    if (sort==='district') return (a.district||'').localeCompare(b.district||'');
    if (sort==='type') return (a.rd||'').localeCompare(b.rd||'');
    if (sort==='price-asc') return (a.p||0)-(b.p||0);
    if (sort==='price-desc') return (b.p||0)-(a.p||0);
    return 0;
  });
  if (countEl) countEl.textContent = favApts.length ? favApts.length + ' ' + (favApts.length===1?'квартира':favApts.length<5?'квартиры':'квартир') : '';
  if (!favApts.length) {
    list.innerHTML = '<div class="fav-panel-empty">Нет избранных квартир</div>';
    return;
  }
  var html = '';
  favApts.forEach(function(apt){
    var oldP = (apt.disc>0 && apt.pb>0) ? '<span class="fav-item-old-price">'+apt.pbs+'</span>' : '';
    html += '<div class="fav-item" onclick="openFavApt(\''+apt.id+'\')">';
    html += '<div class="fav-item-img">';
    html += '<div class="fav-item-img-heart-zone">';
    html += '<button class="fav-item-heart" onclick="event.stopPropagation();removeFav(\''+apt.id+'\')">';
    html += '<svg viewBox="0 0 24 24"><path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6-9 13-9 13z" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    html += '</button></div>';
    html += '<div class="fav-item-img-photo">'+(apt.img?'<img src="'+apt.img+'" onerror="this.style.display=\'none\'">':'')+'</div>';
    html += '</div>';
    html += '<div class="fav-item-info">';
    html += '<div class="fav-item-district">'+(apt.district||'')+'</div>';
    html += '<div class="fav-item-type">'+(apt.rd||'')+(apt.a?' · '+apt.a+' м²':'')+'</div>';
    html += '<div class="fav-item-price">'+(apt.ps||'—')+oldP+'</div>';
    html += '<button class="fav-item-btn" onclick="event.stopPropagation();openFavApt(\''+apt.id+'\');">Получить консультацию</button>';
    html += '</div></div>';
  });
  list.innerHTML = html;
};
// ── Лайки ──────────────────────────────────────────────────
window._aptLikes = {};
try { var _savedCounts = localStorage.getItem('apt_likes_count'); if (_savedCounts) window._aptLikes = JSON.parse(_savedCounts); } catch(e){}
window._likesCallback = function(data) {
  if (!data) return;
  window._aptLikes = data;
};
window.loadLikes = function() {
  if (typeof LIKES_URL === 'undefined' || !LIKES_URL) return;
  fetch(LIKES_URL)
    .then(function(r){ return r.json(); })
    .then(function(data){
      window._aptLikes = data;
      try { localStorage.setItem('apt_likes_count', JSON.stringify(data)); } catch(e){}
    }).catch(function(){
      // fallback to localStorage
      try { var s = localStorage.getItem('apt_likes_count'); if(s) window._aptLikes = JSON.parse(s); } catch(e){}
    });
};
window.sendLike = function(aptId, jk, action) {
  if (typeof LIKES_URL === 'undefined' || !LIKES_URL) return;
  var url = LIKES_URL + '?apt_id=' + encodeURIComponent(aptId) + '&jk=' + encodeURIComponent(jk||'') + '&action=' + encodeURIComponent(action);
  var img = new Image();
  img.src = url;
};
window.openFavApt = function(aptId) {
  var apt = window._allApts && window._allApts.find(function(a){ return a.id===aptId; });
  if (apt) openAptCard(apt);
};
window._favToastTimer = null;
window.showFavToast = function(added) {
  var el = document.getElementById('fav-toast');
  if (!el) return;
  var iconEl = el.querySelector('svg');
  var fullHeart = '<path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6-9 13-9 13z" stroke-linecap="round" stroke-linejoin="round"/>';
  var brokenHeart = '<path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6-9 13-9 13z" stroke-linecap="round" stroke-linejoin="round"/><polyline points="12 8 10 12 14 14 12 18" stroke-width="1.5"/>';
  if (iconEl) iconEl.innerHTML = added ? fullHeart : brokenHeart;
  el.querySelector('span').textContent = added ? '\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e \u0432 \u0438\u0437\u0431\u0440\u0430\u043d\u043d\u043e\u0435' : '\u0423\u0434\u0430\u043b\u0435\u043d\u043e \u0438\u0437 \u0438\u0437\u0431\u0440\u0430\u043d\u043d\u043e\u0433\u043e';
  el.classList.add('visible');
  clearTimeout(window._favToastTimer);
  window._favToastTimer = setTimeout(function(){ el.classList.remove('visible'); }, 2000);
};
window.removeFav = function(aptId) {
  window._favourites = (window._favourites||[]).filter(function(id){ return id!==aptId; });
  var card = document.querySelector('[data-apt-id="'+aptId+'"]');
  if (card) { var btn = card.querySelector('.apt-heart'); if (btn) btn.classList.remove('liked'); }
  updateFavTrack();
  window.renderFavPanel();
  window.showFavToast(false);
};
window.shareFavourites = function() {
  var favIds = window._favourites || [];
  if (!favIds.length) return;
  var url = window.location.href.split('?')[0] + '?favs=' + favIds.join(',');
  var text = '\u041f\u043e\u0434\u0431\u043e\u0440\u043a\u0430 \u043a\u0432\u0430\u0440\u0442\u0438\u0440: ' + url;
  if (navigator.share) {
    navigator.share({ title: '\u041f\u043e\u0434\u0431\u043e\u0440\u043a\u0430 \u043a\u0432\u0430\u0440\u0442\u0438\u0440', text: text, url: url });
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(url).then(function(){
      var btn = document.querySelector('[onclick*="shareFavourites"]');
      if (btn) { var orig = btn.innerHTML; btn.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>'; setTimeout(function(){ btn.innerHTML = orig; }, 1500); }
    });
  }
};
window.openFavSortPopup = function() {
  var cur = window._favSort || 'district';
  var items = [['district','По району'],['type','По формату'],['price-asc','Сначала дешевле'],['price-desc','Сначала дороже']];
  var html = '<div style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:5000" onclick="this.remove()">';
  html += '<div style="position:absolute;bottom:0;left:0;right:0;background:#fff;border-radius:20px 20px 0 0;padding:24px 20px 40px" onclick="event.stopPropagation()">';
  html += '<div style="font-size:17px;font-weight:600;margin-bottom:8px">Сортировать</div>';
  items.forEach(function(item){
    var active = cur===item[0];
    html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:16px 0;border-bottom:1px solid #f0f0f0;cursor:pointer" onclick="window._favSort=\''+item[0]+'\';document.querySelector(\'[data-fav-sort]\').remove();window.renderFavPanel()">';
    html += '<span style="font-size:16px;font-weight:300">'+item[1]+'</span>';
    html += '<div style="width:22px;height:22px;border-radius:50%;border:2px solid '+(active?'#e8244b':'#d0d0d0')+';display:flex;align-items:center;justify-content:center">';
    if (active) html += '<div style="width:10px;height:10px;border-radius:50%;background:#e8244b"></div>';
    html += '</div></div>';
  });
  html += '</div></div>';
  var el = document.createElement('div');
  el.setAttribute('data-fav-sort','');
  el.innerHTML = html;
  document.body.appendChild(el);
};
window.setFavSort = function(btn, sort) {
  document.querySelectorAll('.fav-sort-btn').forEach(function(b){ b.classList.remove('active'); });
  btn.classList.add('active');
};
function roomMatches(apt) {
if (currentRooms.includes('all')) return true;
const rInt = parseInt(apt.r, 10);
for (const val of currentRooms) {
if (val === '3plus') { if (!isNaN(rInt) && rInt >= 3) return true; }
else if (apt.r === val) return true;
}
return false;
}
function finishMatches(apt) {
if (!selectedFinishes.length) return true;
return selectedFinishes.includes(apt.finish);
}
// ── Свайп карточек (touch + mouse) — глобальные функции ──────────────────
let _swipeX0 = 0, _swipeY0 = 0, _swiping = false;
window.aptSwipeStart = function(e){
  const t = e.touches ? e.touches[0] : e;
  _swipeX0 = t.clientX; _swipeY0 = t.clientY; _swiping = true;
  // Preload соседних рендеров сразу при касании — чтобы к концу свайпа картинка уже была в кэше
  const wrapper = e.target && e.target.closest('.apt-plan-wrapper');
  if(wrapper){
    const cur = parseInt(wrapper.dataset.slide || 0);
    const renders = (wrapper.dataset.renders || '').split(',').filter(Boolean);
    [cur, cur+1].forEach(function(i){ if(i>0 && renders[i-1]){ var pi=new Image(); pi.src=renders[i-1]; } });
  }
}
window.aptSwipeMove = function(e){
  if(!_swiping) return;
  const t = e.touches ? e.touches[0] : e;
  const dx = Math.abs(t.clientX - _swipeX0);
  const dy = Math.abs(t.clientY - _swipeY0);
  if(dx > dy && dx > 5) e.preventDefault();
}
window.aptSwipeEnd = function(e, el){
  if(!_swiping){ return; } _swiping = false;
  const t = e.changedTouches ? e.changedTouches[0] : e;
  const dx = t.clientX - _swipeX0;
  if(Math.abs(dx) < 20) return;
  const wrapper = (el && el.classList && el.classList.contains('apt-plan-wrapper')) ? el : el?.closest('.apt-plan-wrapper');
  const total = parseInt(wrapper.dataset.total || 1);
  if(total <= 1) return;
  let cur = parseInt(wrapper.dataset.slide || 0);
  cur = dx < 0 ? Math.min(cur+1, total-1) : Math.max(cur-1, 0);
  aptGoSlide(wrapper, cur);
}
function aptGoSlide(wrapper, idx){
  wrapper.dataset.slide = idx;
  wrapper.querySelectorAll('.apt-dot').forEach((d,i)=>{ d.classList.toggle('active', i===idx); });
  const overlay = wrapper.querySelector('.apt-render-overlay');
  if(idx > 0){
    const renders = (wrapper.dataset.renders || '').split(',').filter(Boolean);
    const src = renders[idx-1];
    if(src && overlay){
      // Показываем оверлей только после загрузки картинки — иначе мелькает план
      let shown = false;
      const show = function(){
        if(shown) return; shown = true;
        overlay.style.backgroundImage = 'url('+src+')';
        overlay.style.display = 'block';
        wrapper.classList.add('show-render');
      };
      const tmp = new Image();
      tmp.onload  = show;
      tmp.onerror = show; // показываем даже при ошибке — лучше чем ничего
      tmp.src = src;
      if(tmp.complete) show(); // картинка уже в кэше — показываем мгновенно
    }
  } else {
    if(overlay){ overlay.style.display = 'none'; overlay.style.backgroundImage = ''; }
    wrapper.classList.remove('show-render');
  }
}

window._allApts = apartmentsData;

// ── Быстрые подборки ──────────────────────────────────────────
// Данные подставляются из window._qcData (inline script в HTML)
(function() {
  var cats = window._qcData || [];
  var grid = document.getElementById('qc-grid');
  if (!grid || !cats.length) return;
  var arr = '<svg viewBox="0 0 24 24"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';
  cats.forEach(function(cat) {
    var tile = document.createElement('div');
    tile.className = 'qc-tile';
    tile.innerHTML =
      '<img src="' + cat.img + '" alt="' + cat.title + '" loading="lazy">' +
      '<div class="qc-ov"></div>' +
      '<span class="qc-tag">' + cat.tag + '</span>' +
      '<div class="qc-body">' +
        '<div class="qc-title">' + cat.title + '</div>' +
        '<div class="qc-sub">' + cat.sub + '</div>' +
      '</div>' +
      '<div class="qc-arr">' + arr + '</div>';
    tile.addEventListener('click', function() { applyQuickCategory(cat); });
    grid.appendChild(tile);
  });
})();

window.applyQuickCategory = function(cat) {
  var banner = document.getElementById('qc-banner');
  var bannerText = document.getElementById('qc-banner-text');
  if (banner) { bannerText.textContent = cat.title; banner.classList.add('visible'); }
  var container = document.getElementById('flats-container');
  document.querySelectorAll('#flats-container .apt-card').forEach(function(c) { c.style.display = 'none'; });
  cat.ids.forEach(function(id) {
    var card = document.querySelector('[data-apt-id="' + id + '"]');
    if (card) { container.appendChild(card); card.style.display = 'flex'; }
  });
  var cnt = cat.ids.length;
  var tv = declOfNum(cnt, ['вариант','варианта','вариантов']);
  var tf = declOfNum(cnt, ['Найден','Найдено','Найдено']);
  document.querySelector('.found-counter-wrapper').innerHTML = tf + ': <span class="count-num">' + cnt + '</span> ' + tv;
  document.getElementById('load-more-btn').style.display = 'none';
  document.getElementById('no-results').style.display = cnt === 0 ? 'block' : 'none';
  document.getElementById('main-filter-container').scrollIntoView({behavior:'smooth'});
};

window.resetQuickCategory = function() {
  var banner = document.getElementById('qc-banner');
  if (banner) banner.classList.remove('visible');
  isFirstLoad = false;
  filterApartments();
};
// Восстанавливаем лайки из localStorage
try { var _saved = localStorage.getItem('apt_likes'); if (_saved) window._favourites = JSON.parse(_saved); } catch(e){}
// Карточки уже в DOM (pre-rendered Python). Добавляем класс loaded плану после загрузки.
document.querySelectorAll('.apt-plan').forEach(img => {
  if (img.complete) img.classList.add('loaded');
});
// Восстанавливаем состояние сердечек
// ── Кнопка консультации (аватар убран) ──────────────
window._initAvatarAnim = function() {};

window.syncHearts = function(){
  var favs = window._favourites || [];
  favs.forEach(function(aptId){
    var btn = document.querySelector('[data-apt-id="'+aptId+'"] .apt-heart');
    if (btn) btn.classList.add('liked');
  });
  updateFavTrack();
};
setTimeout(window.syncHearts, 100);
function makeCfg(key, step, fmtObj) {
const r = sliderRanges[key];
if (!r) return null;
const range = (r.nonlinear && r.break80 < r.max)
? { 'min': r.min, '80%': r.break80, 'max': r.max }
: { 'min': r.min, 'max': r.max };
const base = { start: [r.min, r.max], connect: true, range, step };
return fmtObj
? { ...base, tooltips: [fmtObj, fmtObj] }
: base;
}
const fmtA = { to: v => `${Math.round(v)} м²`,  from: v => parseFloat(v) };
const fmtP = {
to:   v => v >= 1000000 ? `${(v / 1000000).toFixed(1)} млн` : `${Math.round(v / 1000)} т`,
from: v => { const s = String(v); return s.includes('млн') ? parseFloat(s) * 1e6 : parseFloat(s) * 1e3; }
};
window.SL = {};
const SL = window.SL;
[
['d-slider-area',  makeCfg('a', 0.5,   null)],
['d-slider-price', makeCfg('p', 50000, null)],
['m-slider-area',        makeCfg('a', 0.5,   fmtA)],
['m-slider-price',       makeCfg('p', 50000, fmtP)],
['m-inline-slider-area', makeCfg('a', 0.5,   fmtA)],
['m-inline-slider-price',makeCfg('p', 50000, fmtP)],
['d-modal-slider-area',  makeCfg('a', 0.5,   null)],
['d-modal-slider-price', makeCfg('p', 50000, null)],
].forEach(([id, cfg]) => {
if (!cfg) return;
const el = document.getElementById(id);
if (el) { noUiSlider.create(el, cfg); SL[id] = el; }
});
function updateLabels() {
const d = window.innerWidth > 900;
const sA = SL[d ? 'd-slider-area'  : 'm-inline-slider-area'];
const sP = SL[d ? 'd-slider-price' : 'm-inline-slider-price'];
if (!sA) return;
const [a0, a1] = sA.noUiSlider.get().map(parseFloat);
const [p0, p1] = sP.noUiSlider.get().map(parseFloat);
[
[['d-area-val',  'd-modal-area-val'],  `${Math.round(a0)}–${Math.round(a1)} м²`],
[['d-price-val', 'd-modal-price-val'], `${fmtP.to(p0)}–${fmtP.to(p1)}`],
].forEach(([ids, txt]) => ids.forEach(id => { const el = document.getElementById(id); if (el) el.innerText = txt; }));
}
function syncSliders(src) {
if (isSyncing) return; isSyncing = true;
const groups = [
['d-slider-area',  'm-slider-area',  'm-inline-slider-area',  'd-modal-slider-area'],
['d-slider-price', 'm-slider-price', 'm-inline-slider-price', 'd-modal-slider-price'],
];
const SI = { desktop: 0, mobile: 1, inline: 2, dmodal: 3 };
const si = SI[src] ?? 0;
groups.forEach(g => {
const m = SL[g[si]]; if (!m) return;
const v = m.noUiSlider.get();
g.forEach((id, i) => { if (i !== si && SL[id]) SL[id].noUiSlider.set(v); });
});
isSyncing = false;
}
function updateSliderRange(key, vals, newMin, newMax) {
  if (window._sliderActive) return;
  const ids = key === 'a'
    ? ['d-slider-area','m-slider-area','m-inline-slider-area','d-modal-slider-area']
    : ['d-slider-price','m-slider-price','m-inline-slider-price','d-modal-slider-price'];
  // Реальный P90 по данным
  const p90 = vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.9))];
  const nonlinear = newMax > p90 * 1.5;
  const range = (nonlinear && p90 < newMax)
    ? { 'min': newMin, '80%': p90, 'max': newMax }
    : { 'min': newMin, 'max': newMax };
  ids.forEach(function(id) {
    const sl = SL[id]; if (!sl || !sl.noUiSlider) return;
    sl.noUiSlider.updateOptions({ range }, false);
    sl.noUiSlider.set([newMin, newMax]);
  });
}
window.filterApartments = function filterApartments(loadMore = false) {if (!loadMore) showCount = step;
const d = window.innerWidth > 900;
const sA = SL[d ? 'd-slider-area'  : 'm-inline-slider-area'];
const sP = SL[d ? 'd-slider-price' : 'm-inline-slider-price'];
if (!sA) return;

// Сначала пересчитываем диапазоны по текущим фильтрам (без слайдеров)
const nonSliderFiltered = apartmentsData.filter(apt => {
  const dOk = !selectedMapDistricts.length || (apt.district && selectedMapDistricts.some(function(d) { return apt.district.toLowerCase() === d.toLowerCase(); }));
  return dOk && roomMatches(apt) && finishMatches(apt);
});
if (nonSliderFiltered.length > 0 && !loadMore) {
  const areas  = nonSliderFiltered.filter(a => a.a > 0).map(a => a.a).sort((a,b) => a-b);
  const prices = nonSliderFiltered.filter(a => a.p > 0).map(a => a.p).sort((a,b) => a-b);
  if (areas.length)  updateSliderRange('a', areas,  areas[0],  areas[areas.length-1]);
  if (prices.length) updateSliderRange('p', prices, prices[0], prices[prices.length-1]);
}

// Читаем значения слайдеров ПОСЛЕ обновления диапазонов
const [aMin, aMax] = sA.noUiSlider.get().map(parseFloat);
const [pMin, pMax] = sP.noUiSlider.get().map(parseFloat);
const absMaxA = sliderRanges.a ? sliderRanges.a.max : aMax;
const absMaxP = sliderRanges.p ? sliderRanges.p.max : pMax;

updateLabels();
matched = [];
const allCards = document.querySelectorAll('#flats-container .apt-card');
allCards.forEach(el => el.style.display = 'none');
allCards.forEach(el => {
const p = parseFloat(el.dataset.p) || 0;
const a = parseFloat(el.dataset.a) || 0;
const aOk = a === 0 || (a >= aMin && (aMax >= absMaxA || a <= aMax));
const pOk = p === 0 || (p >= pMin && (pMax >= absMaxP || p <= pMax));
const district = el.dataset.district || '';
const dOk = !selectedMapDistricts.length || (district && selectedMapDistricts.some(function(d) { return district.toLowerCase() === d.toLowerCase(); }));
const apt = {r: el.dataset.r, p, a, finish: el.dataset.finish, district, onreq: el.dataset.onreq === '1'};
if (aOk && pOk && dOk && roomMatches(apt) && finishMatches(apt)) matched.push({el, apt});
});
if (currentSort) {
  const [key, dir] = currentSort.split('-');
  matched.sort((a, b) => {
    const va = key === 'price' ? a.apt.p : a.apt.a;
    const vb = key === 'price' ? b.apt.p : b.apt.a;
    if (key === 'price') {
      if (va === 0 && vb === 0) return 0;
      if (va === 0) return 1;
      if (vb === 0) return -1;
    }
    return dir === 'asc' ? va - vb : vb - va;
  });
}
// Скрываем все карточки
matched.forEach(m => m.el.style.display = 'none');
// Переставляем DOM в нужном порядке и показываем первые showCount
matched.forEach(m => container.appendChild(m.el));
matched.slice(0, showCount).forEach(m => m.el.style.display = 'flex');
const cnt = matched.length;
const tv = declOfNum(cnt, ['вариант', 'варианта', 'вариантов']);
const tf = declOfNum(cnt, ['Найден', 'Найдено', 'Найдено']);
document.querySelector('.found-counter-wrapper').innerHTML = `${tf}: <span class="count-num">${cnt}</span> ${tv}`;
mApplyBtn.innerText     = `Показать ${cnt} ${tv}`;
dModalApplyBtn.innerText = `Показать ${cnt} ${tv}`;
mFloatTxt.innerText     = isFirstLoad ? 'Фильтры' : `${tf} ${cnt} ${tv}`;
const mtbCountEl = document.getElementById('mtb-count-text');
if (mtbCountEl) mtbCountEl.textContent = `Найдено ${cnt} ${tv}`;
if (cnt > 0 && window.scrollY > 100) mFloatBtn.classList.add('visible');
loadBtn.style.display = (cnt > showCount) ? 'inline-block' : 'none';
noRes.style.display   = (cnt === 0) ? 'block' : 'none';

}

document.querySelectorAll('.sort-btn').forEach(btn => btn.addEventListener('click', function() {
  const val = this.dataset.sort;
  if (currentSort === val) { currentSort = null; document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active')); }
  else { currentSort = val; document.querySelectorAll('.sort-btn').forEach(b => b.classList.toggle('active', b.dataset.sort === val)); }
  isFirstLoad = false; updateMtbState(); filterApartments();
}));

roomBtns.forEach(btn => btn.addEventListener('click', function () {
const val = this.dataset.room;
if (val === 'all') { currentRooms = ['all'];
  // Reset sliders to initial range
  try {
    var _sr = window.sliderRanges;
    ['m-inline-slider-area','d-slider-area'].forEach(function(k){
      if (window.SL[k]) window.SL[k].noUiSlider.set([_sr.a.min, _sr.a.max]);
    });
    ['m-inline-slider-price','d-slider-price'].forEach(function(k){
      if (window.SL[k]) window.SL[k].noUiSlider.set([_sr.p.min, _sr.p.max]);
    });
    // Принудительно фиксируем позиции тултипов
    requestAnimationFrame(function(){ requestAnimationFrame(function(){
      ['m-inline-slider-area','m-inline-slider-price','m-slider-area','m-slider-price'].forEach(function(k){
        var sl = SL[k]; if (!sl) return;
        var tt = sl.querySelectorAll('.noUi-tooltip');
        if (tt.length < 2) return;
        var ttW0 = tt[0].offsetWidth;
        if (ttW0) tt[0].style.transform = 'translateX(calc(-50% + ' + Math.ceil(ttW0/2 - 10) + 'px))';
        var ttW1 = tt[1].offsetWidth;
        if (ttW1) tt[1].style.transform = 'translateX(calc(-50% - ' + Math.ceil(ttW1/2 - 10) + 'px))';
      });
    }); });
  } catch(e){}
}
else {
const ai = currentRooms.indexOf('all'); if (ai > -1) currentRooms.splice(ai, 1);
const i  = currentRooms.indexOf(val);
if (i > -1) currentRooms.splice(i, 1); else currentRooms.push(val);
if (!currentRooms.length) currentRooms = ['all'];
}
roomBtns.forEach(b => { if (currentRooms.includes(b.dataset.room)) b.classList.add('active'); else b.classList.remove('active'); });
isFirstLoad = false; updateMtbState(); filterApartments();
}));
finishCbs.forEach(cb => cb.closest('label').addEventListener('click', function (e) {
if (e.target.tagName === 'INPUT') return; e.preventDefault();
const val = this.querySelector('input').value;
if (selectedFinishes.includes(val)) selectedFinishes = selectedFinishes.filter(f => f !== val);
else selectedFinishes.push(val);
finishCbs.forEach(c => {
const lbl = c.closest('label');
const active = selectedFinishes.includes(c.value);
c.checked = active;
if (lbl) { if (active) lbl.classList.add('active'); else lbl.classList.remove('active'); }
});
isFirstLoad = false; filterApartments();
}));
function smartRepel(slider) {
  var tt = slider.target.querySelectorAll('.noUi-tooltip');
  if (tt.length < 2) return;
  var t0 = tt[0], t1 = tt[1];
  var tr = slider.target.getBoundingClientRect();
  if (!tr.width) return;
  var GAP = 8;
  // Reset transforms
  t0.style.transform = 'translateX(-50%)';
  t1.style.transform = 'translateX(-50%)';
  // Force reflow
  void slider.target.offsetWidth;
  var r0 = t0.getBoundingClientRect();
  var r1 = t1.getBoundingClientRect();
  var clamp0 = 0, clamp1 = 0;
  // Clamp left boundary
  if (r0.left < tr.left) {
    clamp0 = tr.left - r0.left;
    t0.style.transform = 'translateX(calc(-50% + ' + Math.ceil(clamp0) + 'px))';
  }
  // Clamp right boundary
  if (r1.right > tr.right) {
    clamp1 = r1.right - tr.right;
    t1.style.transform = 'translateX(calc(-50% - ' + Math.ceil(clamp1) + 'px))';
  }
  // Re-measure after clamping
  r0 = t0.getBoundingClientRect();
  r1 = t1.getBoundingClientRect();
  // Repel if overlapping
  var ov = (r0.right + GAP) - r1.left;
  if (ov > 0) {
    var pushL = Math.ceil(ov / 2);
    var pushR = Math.ceil(ov / 2);
    var spL = r0.left - tr.left;
    var spR = tr.right - r1.right;
    if (spL < pushL) { pushR += pushL - spL; pushL = spL; }
    if (spR < pushR) { pushL += pushR - spR; pushR = spR; }
    t0.style.transform = 'translateX(calc(-50% + ' + (Math.ceil(clamp0) - pushL) + 'px))';
    t1.style.transform = 'translateX(calc(-50% - ' + (Math.ceil(clamp1) - pushR) + 'px))';
  }
}
window.debugSlider = function() {
  var k = 'm-inline-slider-price';
  var sl = SL[k]; if (!sl) { console.log('SL['+k+'] not found'); return; }
  var tt = sl.querySelectorAll('.noUi-tooltip');
  var origins = sl.querySelectorAll('.noUi-origin');
  var trackW = sl.offsetWidth;
  console.log('trackW:', trackW);
  console.log('tt count:', tt.length, 'origins count:', origins.length);
  [0,1].forEach(function(i){
    var handles2 = sl.querySelectorAll('.noUi-handle');
    var hRect = handles2[i] ? handles2[i].getBoundingClientRect() : null;
    var trRect = sl.getBoundingClientRect();
    var handleCX = hRect ? (hRect.left + hRect.width/2 - trRect.left) : 'N/A';
    var ttW = tt[i] ? tt[i].offsetWidth : 0;
    console.log('handle'+i+': handleCenterX='+handleCX+' trackW='+trRect.width+' ttW='+ttW+' transform='+(tt[i]?tt[i].style.transform:'N/A'));
  });
};
[
['d-slider-area','desktop'],  ['d-slider-price','desktop'],
['m-slider-area','mobile'],   ['m-slider-price','mobile'],
['m-inline-slider-area','inline'], ['m-inline-slider-price','inline'],
['d-modal-slider-area','dmodal'],  ['d-modal-slider-price','dmodal'],
].forEach(([id, src]) => {
const sl = SL[id]; if (!sl) return;
const isMobile = src === 'mobile' || src === 'inline';
sl.noUiSlider.on('start', () => { window._sliderActive = true; });
sl.noUiSlider.on('end',   () => { window._sliderActive = false; });
sl.noUiSlider.on('update', () => {
syncSliders(src);
updateLabels();
if (window._repelRAF) cancelAnimationFrame(window._repelRAF);
window._repelRAF = requestAnimationFrame(function(){
  ['m-inline-slider-area','m-inline-slider-price','m-slider-area','m-slider-price'].forEach(function(k){
    if (SL[k] && SL[k].noUiSlider) smartRepel(SL[k].noUiSlider);
  });
});
});
sl.noUiSlider.on('change', () => { isFirstLoad = false; updateMtbState(); filterApartments(); });
});
loadBtn.addEventListener('click', () => { showCount += step; filterApartments(true); });
document.querySelectorAll('.sort-btn[data-sort="price-asc"]').forEach(b => b.classList.add('active'));
filterApartments();
if (window.loadLikes) window.loadLikes();
// Fix initial tooltip positions
setTimeout(function(){
  Object.keys(SL).forEach(function(k){
    if (SL[k] && SL[k].noUiSlider) smartRepel(SL[k].noUiSlider);
  });
}, 300);
window.addEventListener('scroll', () => {
const r = document.getElementById('main-filter-container').getBoundingClientRect();
if (r.top < window.innerHeight && r.bottom > 0 && window.scrollY > 300) mFloatBtn.classList.add('visible');
else mFloatBtn.classList.remove('visible');
const mTopBar = document.getElementById('mobile-top-bar');
if (mTopBar && window.innerWidth <= 900) {
  const counter = document.querySelector('.found-counter-wrapper');
  if (counter) {
    const rect = counter.getBoundingClientRect();
    if (rect.bottom < 0) mTopBar.classList.add('visible');
    else if (rect.bottom > 60) mTopBar.classList.remove('visible');
  }
}
});
const imgOverlay = document.getElementById('img-modal-overlay');
const bigImg     = document.getElementById('img-modal-img');
function closeImg() { imgOverlay.classList.remove('active'); document.body.style.overflow = ''; setTimeout(() => bigImg.src = '', 300); }
document.querySelector('.img-modal-close').addEventListener('click', closeImg);
imgOverlay.addEventListener('click', e => { if (e.target === imgOverlay) closeImg(); });
container.addEventListener('click', e => {
  const card = e.target.closest('.apt-card');
  if (!card) return;
  if (e.target.closest('.apt-heart')) return;
  const aptId = card.dataset.aptId;
  const apt = apartmentsData.find(a => a.id === aptId);
  if (apt) openAptCard(apt);
});
// Авто-открытие карточки по ?apt= в URL
(function() {
  var params = new URLSearchParams(window.location.search);
  var aptId = params.get('apt');
  if (!aptId) return;
  var apt = apartmentsData.find(function(a){ return a.id === aptId; });
  if (apt) setTimeout(function(){ openAptCard(apt); }, 400);
})();
}); // end DOMContentLoaded
"""
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Каталог квартир</title>
<!-- Preload hero image -->
<!-- hero img вшит в HTML — браузер загружает его автоматически с высоким приоритетом -->
<!-- Google Fonts async -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@300;400;500;600;700&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
<noscript><link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@300;400;500;600;700&display=swap" rel="stylesheet"></noscript>
<!-- noUiSlider CSS inline (tiny) -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/noUiSlider/15.7.0/nouislider.min.css">
<!-- noUiSlider JS defer -->
<!-- noUiSlider загружается вместе с фильтром -->
<link rel="stylesheet" href="{YANDEX_CLOUD_BASE_URL}/filter.css?v={BUILD_VERSION}">
</head>
<body>

<!-- ═══════════════════════════ HERO ═══════════════════════════ -->
<style>
.hero-s{{position:relative;width:100%;height:100vh;min-height:560px;overflow:hidden;font-family:'Inter Tight',sans-serif}}
@supports(height:100svh){{.hero-s{{height:100svh}}}}
.hero-slides{{position:absolute;top:0;left:0;right:0;bottom:0;z-index:0}}
.hero-slide{{position:absolute;top:0;left:0;right:0;bottom:0;opacity:0;transition:opacity 2.5s ease-in-out;will-change:opacity}}
.hero-slide.active{{opacity:1}}
.hero-slide img{{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;object-position:center top;display:block;}}
.hero-ov{{position:absolute;inset:0;z-index:1;background:linear-gradient(to top,rgba(8,10,15,.92) 0%,rgba(8,10,15,.4) 40%,transparent 65%),linear-gradient(to bottom,rgba(8,10,15,.65) 0%,transparent 28%)}}
.hero-nav{{position:absolute;top:0;left:0;right:0;z-index:10;display:flex;align-items:center;justify-content:space-between;padding:24px 48px}}
.hero-logo img{{height:52px;display:block}}
.hero-cnt{{display:flex;align-items:center;gap:20px}}
.hero-cnt a{{display:flex;align-items:center;color:rgba(255,255,255,.88);text-decoration:none;transition:color .2s}}
.hero-cnt a:hover{{color:#CBA363}}
.hero-cnt svg{{width:22px;height:22px;fill:currentColor}}
.hero-phone{{font-size:15px;font-weight:500;color:rgba(255,255,255,.92)!important;white-space:nowrap}}
.hero-div{{width:1px;height:20px;background:rgba(255,255,255,.25)}}
.hero-body{{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;justify-content:flex-end;padding:0 48px 88px;max-width:860px}}
.hero-tag{{font-size:13px;letter-spacing:.08em;color:rgba(255,255,255,.90);margin-bottom:18px;text-shadow:0 1px 4px rgba(0,0,0,.6)}}
.hero-h1{{font-size:clamp(38px,6vw,72px);font-weight:700;line-height:1.08;letter-spacing:-.02em;margin-bottom:28px;color:#fff}}
.hero-h1 .hero-gold{{color:#CBA363;display:block}}
.hero-buls{{display:flex;flex-direction:column;gap:8px;margin-bottom:40px}}
.hero-bul{{font-size:15px;color:rgba(255,255,255,.78);display:flex;align-items:center;gap:10px}}
.hero-bul::before{{content:'';display:inline-block;width:18px;height:1px;background:#CBA363;flex-shrink:0}}
.hero-cta{{position:relative;overflow:hidden;display:inline-flex;align-items:center;gap:10px;background:#CBA363;color:#0d1117;font-size:14px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;text-decoration:none;padding:14px 28px;border-radius:2px;width:fit-content;transition:transform .2s;font-family:'Inter Tight',sans-serif}}
.hero-cta:hover{{transform:scale(1.03)}}
.hero-cta::before{{content:'';position:absolute;top:0;left:-75%;width:50%;height:100%;background:linear-gradient(120deg,rgba(255,255,255,0) 0%,rgba(255,255,255,0.4) 50%,rgba(255,255,255,0) 100%);transform:skewX(-20deg);animation:hero-shine 3s infinite;pointer-events:none}}
@keyframes hero-shine{{0%{{left:-75%}}50%{{left:125%}}100%{{left:125%}}}}
.hero-dots{{position:absolute;bottom:36px;right:48px;z-index:10;display:flex;gap:8px;align-items:center}}
.hero-dot{{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.30);cursor:pointer;border:none;transition:background .3s,transform .3s;padding:0}}
.hero-dot.active{{background:#CBA363;transform:scale(1.5)}}
.hero-pb{{position:absolute;bottom:0;left:0;height:2px;background:#CBA363;z-index:10;width:0}}
@media(max-width:768px){{
  .hero-nav{{padding:16px 20px}}
  .hero-logo img{{height:38px}}
  .hero-phone{{display:none}}
  .hero-body{{padding:0 20px 72px}}
  .hero-h1{{font-size:clamp(30px,8vw,44px)}}
  .hero-tag{{font-size:11px;margin-bottom:12px}}
  .hero-bul{{font-size:13px}}
  .hero-buls{{gap:6px;margin-bottom:28px}}
  .hero-cta{{font-size:13px;padding:12px 22px}}
  .hero-dots{{right:20px;bottom:24px}}
}}
</style>
<section class="hero-s">
  <div class="hero-slides" id="hero-sl">
    <div class="hero-slide active">
      <img src="{YANDEX_CLOUD_BASE_URL}/background/Terrace_SPB_RoyaltyPlace%282%29_mob.webp?v=1"
           alt="Квартиры с террасами Санкт-Петербург"
           fetchpriority="high"
           decoding="async">
    </div>
  </div>
  <div class="hero-ov"></div>
  <nav class="hero-nav">
    <a class="hero-logo" href="/"><img src="{YANDEX_CLOUD_BASE_URL}/background/Royalty_Place_White_1%40.svg" alt="Royalty Place"></a>
    <div class="hero-cnt">
      <a href="https://t.me/royaltyplace_spb" title="Telegram"><svg viewBox="0 0 24 24"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248-2.04 9.607c-.15.666-.546.83-1.107.516l-3.07-2.263-1.48 1.423c-.164.164-.3.3-.616.3l.22-3.115 5.67-5.12c.247-.22-.054-.342-.383-.122L7.19 14.49l-3.01-.94c-.654-.204-.667-.654.137-.968l11.754-4.532c.545-.197 1.022.122.49.198z"/></svg></a>
      <a href="https://max.ru/join/is7qpZrXePlRpIi1ClliKPk6EPhOB6iIFius8BrTQK8" title="MAX"><img src="{YANDEX_CLOUD_BASE_URL}/background/Max_logo.svg" alt="MAX" style="width:22px;height:22px;display:block;filter:brightness(0) invert(1);opacity:.88;"></a>
      <div class="hero-div"></div>
      <a href="tel:+78124158505" class="hero-phone">+7 (812) 415-85-05</a>
    </div>
  </nav>
  <div class="hero-body">
    <p class="hero-tag">Эксклюзивные предложения от Royalty Place</p>
    <h1 class="hero-h1">Все квартиры<br>Санкт-Петербурга<span class="hero-gold">с террасами</span></h1>
    <div class="hero-buls">
      <div class="hero-bul">рассрочки до 5 лет</div>
      <div class="hero-bul">все районы Санкт-Петербурга</div>
      <div class="hero-bul">резиденции с видами на воду и город</div>
      <div class="hero-bul">напрямую от застройщиков</div>
    </div>
    <a href="#main-filter-container" class="hero-cta" onclick="event.preventDefault();document.getElementById('main-filter-container').scrollIntoView({{behavior:'smooth'}})">Смотреть квартиры ↓</a>
  </div>
  <div class="hero-dots" id="hero-dots"></div>
  <div class="hero-pb" id="hero-pb"></div>
</section>
<!-- hero-slide вшит в HTML напрямую, JS для слайдов не нужен -->
<!-- ═══════════════════════════════════════════════════════════ -->

<!-- БЫСТРЫЕ ПОДБОРКИ -->
<section class="qc-section">
  <div class="qc-inner">
    <p class="qc-label">Быстрые подборки</p>
    <div class="qc-grid" id="qc-grid"></div>
  </div>
</section>
<script>window._qcData = {qc_data};</script>

<div class="real-estate-filter" id="main-filter-container">
<div id="img-modal-overlay" class="img-modal-overlay"><div class="img-modal-close">&times;</div><img id="img-modal-img" class="img-modal-img" src=""></div>

<!-- APARTMENT CARD OVERLAY -->
<div id="apt-card-overlay">
  <div class="apc-header">
    <button class="apc-header-btn" onclick="closeAptCard()">
      <svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
    <div class="apc-header-right">
      <button class="apc-header-btn" onclick="shareApt()">
        <svg viewBox="0 0 24 24"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
      </button>
      <button class="apc-header-btn" id="apc-likes-btn" onclick="toggleApcHeart(this)">
        <div style="display:flex;flex-direction:column;align-items:center;gap:1px">
          <svg viewBox="0 0 24 24" id="apc-heart-svg" style="width:16px;height:16px;stroke:#1a1a1a;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;transition:stroke 0.2s,fill 0.2s"><path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6-9 13-9 13z"/></svg>
          <span class="apc-likes" id="apc-likes-count">0</span>
        </div>
      </button>
    </div>
  </div>
  <div class="apc-plan-area" id="apc-plan-area">
    <div class="apc-slides" id="apc-slides"></div>
    <div class="apc-inline-dots" id="apc-inline-dots"></div>
  </div>

<!-- Fullscreen image popup -->
<div id="apc-img-popup">
  <div class="apc-img-popup-header">
    <div style="width:36px"></div>
    <button class="apc-img-popup-close" onclick="closeImgPopup()">
      <svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  </div>
  <div class="apc-img-popup-slides" id="apc-img-popup-slides">
    <div class="apc-img-popup-track" id="apc-img-popup-track"></div>
  <div class="apc-img-popup-dots" id="apc-img-popup-dots"></div>
  </div>
</div>
  <div class="apc-gallery" id="apc-gallery"></div>
  <div class="apc-body">
    <div class="apc-badge-row" id="apc-badge-row"></div>
    <div class="apc-row"><span class="apc-label">Формат</span><span class="apc-value" id="apc-format"></span></div>
    <div class="apc-row"><span class="apc-label">Площадь</span><span class="apc-value" id="apc-area"></span></div>
    <div class="apc-row"><span class="apc-label">Кухня</span><span class="apc-value" id="apc-kitchen"></span></div>
    <div class="apc-row"><span class="apc-label">Этаж</span><span class="apc-value" id="apc-floor"></span></div>
    <div class="apc-row"><span class="apc-label">Срок сдачи</span><span class="apc-value" id="apc-deadline"></span></div>
    <div class="apc-row"><span class="apc-label">Отделка</span><span class="apc-value" id="apc-finish"></span></div>
    <div class="apc-row"><span class="apc-label">Район</span><span class="apc-value" id="apc-district"></span></div>
    <div class="apc-row apc-view-row" id="apc-view-row" style="display:none"><span class="apc-label apc-view-label"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:-1px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>Видовая квартира</span><span class="apc-value" id="apc-view"></span></div>
    <div class="apc-price-row">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span class="apc-price" id="apc-price"></span>
        <span class="apc-booked-pill" id="apc-booked-label" style="display:none" onclick="_bookedTip(this,event)">В брони<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><polyline points="9,6 15,12 9,18"/></svg><div class="apc-promo-tooltip">Квартира временно забронирована. Цена и статус могут измениться — уточните у менеджера.</div></span>
        <span class="apc-hoff-pill" id="apc-hoff-wrap" style="display:none" onclick="_bookedTip(this,event)"><svg class="apc-hoff-logo" viewBox="0 0 512 300"><path d="M428.5 108H446c11.3 0 20.5 9.2 20.5 20.5S457.3 149 446 149h-17.5v30.5c0 12.4-10.1 22.5-22.5 22.5s-22.5-10.1-22.5-22.5V104c0-30.4 24.6-55 55-55H454c11.3 0 20.5 9.2 20.5 20.5S465.3 90 454 90h-14.5c-6.1 0-11 4.9-11 11v7zm-91.5 0h17.5c11.3 0 20.5 9.2 20.5 20.5s-9.2 20.5-20.5 20.5H337v85.5c0 12.4-10.1 22.5-22.5 22.5S292 246.9 292 234.5V104c0-30.4 24.6-55 55-55h15.5c11.3 0 20.5 9.2 20.5 20.5S373.8 90 362.5 90H348c-6.1 0-11 4.9-11 11v7zM86.5 204.8v29.8c0 12.4-10.1 22.5-22.5 22.5S41.5 247 41.5 234.6v-170C41.5 52.1 51.6 42 64 42s22.5 10.1 22.5 22.5v44h29v-44c0-12.4 10.1-22.5 22.5-22.5s22.5 10.1 22.5 22.5v170c0 12.4-10.1 22.5-22.5 22.5s-22.5-10.1-22.5-22.5v-75c0-6.1-4.9-11-11-11h-18v56.3zM225 96.5h2c30.4 0 55 24.6 55 55V202c0 30.4-24.6 55-55 55h-2c-30.4 0-55-24.6-55-55v-50.5c0-30.4 24.6-55 55-55zm1 40c-6.4 0-11.5 5.1-11.5 11.5v57.5c0 6.4 5.1 11.5 11.5 11.5s11.5-5.1 11.5-11.5V148c0-6.4-5.1-11.5-11.5-11.5zM406 208c13.8 0 25 11.2 25 25s-11.2 25-25 25-25-11.2-25-25 11.2-25 25-25z"/></svg><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><polyline points="9,6 15,12 9,18"/></svg><div class="apc-promo-tooltip" id="apc-hoff-tooltip">Подарочный сертификат Hoff на 50 000 ₽ при покупке квартиры — эксклюзивный бонус для клиентов нашего агентства.</div></span>
      </div>
      <span class="apc-old-price" id="apc-old-price"></span>
    </div>
    <div id="apc-about-block"></div>
    <div id="apc-inst-block"></div>
    <div id="apc-promo-block"></div>
    <div id="apc-mort-block"></div>
    <div id="apc-similar-block"></div>
    <div id="apc-renovation-block">
<div class="apc-finance-divider"></div>
<div class="apc-renovation-spoiler">
  <div class="apc-ren-head" onclick="this.closest('.apc-renovation-spoiler').classList.toggle('apc-ren-open')">
    <div class="apc-ren-title-wrap">
      <div class="apc-ren-title-q">Не хотите заниматься ремонтом самостоятельно?</div>
      <div class="apc-ren-title-s">Воспользуйтесь нашим сервисом <b>«Всё включено»</b></div>
    </div>
    <div class="apc-ren-chev"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 5l4 4 4-4" stroke="#888" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
  </div>
  <div class="apc-ren-body-wrap"><div class="apc-ren-fade"></div><div class="apc-ren-body">
    <div class="apc-ren-subtitle">Мы поможем вам на каждом этапе — от подбора квартиры и одобрения ипотеки до разработки дизайн-проекта и ремонта. Вот как это работает:</div>
    <div class="apc-ren-phase-row"><div class="apc-ren-phase-line"></div><div class="apc-ren-pill apc-ren-pill--blue">Подбор квартиры</div><div class="apc-ren-phase-line"></div></div>
    <div class="apc-ren-timeline">
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--blue">1</div><div class="apc-ren-step-title">Первое обращение</div><div class="apc-ren-step-desc">Рассказываете о задаче — район, бюджет, сроки, пожелания по планировке</div></div>
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--blue">2</div><div class="apc-ren-step-title">Подбор вариантов</div><div class="apc-ren-step-desc">Брокер анализирует рынок и готовит подборку под ваши критерии</div></div>
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--blue">3</div><div class="apc-ren-step-title">Встреча — брокер и дизайнер</div><div class="apc-ren-step-desc">Обсуждаем варианты: брокер — по локации и цене, дизайнер — по потенциалу планировки</div></div>
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--blue">4</div><div class="apc-ren-step-title">Скетч расстановки мебели</div><div class="apc-ren-step-desc">Дизайнер готовит несколько вариантов планировки в масштабе — видите результат до покупки</div></div>
      <div class="apc-ren-step apc-ren-step--last"><div class="apc-ren-dot apc-ren-dot--blue">5</div><div class="apc-ren-step-title">Просмотр объекта</div><div class="apc-ren-step-desc">Выезжаем на объект — для сданных домов вживую, для строящихся — шоу-рум и демо-квартиры</div></div>
    </div>
    <div class="apc-ren-phase-row"><div class="apc-ren-phase-line"></div><div class="apc-ren-pill apc-ren-pill--amber">Сделка</div><div class="apc-ren-phase-line"></div></div>
    <div class="apc-ren-timeline">
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--amber">6</div><div class="apc-ren-step-title">Проведение сделки</div><div class="apc-ren-step-desc">Одобрение ипотеки, согласование индивидуальных условий, оформление договора</div></div>
      <div class="apc-ren-step apc-ren-step--last"><div class="apc-ren-dot apc-ren-dot--amber">7</div><div class="apc-ren-step-title">Договор на дизайн-проект</div><div class="apc-ren-step-desc">Фиксируем условия и объём работ — дизайнер уже в команде</div></div>
    </div>
    <div class="apc-ren-phase-row"><div class="apc-ren-phase-line"></div><div class="apc-ren-pill apc-ren-pill--green">Ремонт и въезд</div><div class="apc-ren-phase-line"></div></div>
    <div class="apc-ren-timeline">
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--green">8</div><div class="apc-ren-step-title">Приёмка квартиры</div><div class="apc-ren-step-desc">Помогаем принять квартиру от застройщика — фиксируем недочёты и добиваемся устранения</div></div>
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--green">9</div><div class="apc-ren-step-title">Разработка дизайн-проекта</div><div class="apc-ren-step-desc">Полный пакет: чертежи, спецификации, 3D-визуализация, ведомость материалов</div></div>
      <div class="apc-ren-step"><div class="apc-ren-step-line"></div><div class="apc-ren-dot apc-ren-dot--green">10</div><div class="apc-ren-step-title">Ремонтные работы</div><div class="apc-ren-step-desc">Бригады-партнёры, работающие с агентством более 7 лет — с авторским надзором дизайнера</div></div>
      <div class="apc-ren-step apc-ren-step--last"><div class="apc-ren-dot apc-ren-dot--green">11</div><div class="apc-ren-step-title">Меблировка и декор</div><div class="apc-ren-step-desc">Подбираем мебель и декор по проекту — с учётом вашего бюджета и сроков доставки</div></div>
    </div>
    <div class="apc-ren-finish">
      <img class="apc-ren-finish-photo" src="https://storage.yandexcloud.net/royaltyplace/terrace/RoyaltyPlace.webp" alt="Квартира готова к жизни" loading="lazy"/>
      <div class="apc-ren-finish-overlay"></div>
      <div class="apc-ren-finish-text">
        <div class="apc-ren-finish-tag">Финал пути</div>
        <div class="apc-ren-finish-title">Квартира готова к жизни</div>
        <div class="apc-ren-finish-sub">Вы заезжаете — всё остальное было на нас</div>
      </div>
    </div>
    <div class="apc-ren-free-banner apc-ren-free-banner--alert">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style="flex-shrink:0;margin-top:1px"><circle cx="8" cy="8" r="6.5" fill="#e8244b" opacity=".15" stroke="#c0182e" stroke-width="1.2"/><line x1="8" y1="4.5" x2="8" y2="9" stroke="#c0182e" stroke-width="1.4" stroke-linecap="round"/><circle cx="8" cy="11" r="0.8" fill="#c0182e"/></svg>
      <div class="apc-ren-free-text apc-ren-free-text--alert"><b>Подбор квартиры и консультация дизайнера — бесплатно.</b> Наши цены не отличаются от цен застройщика: комиссию агентства оплачивает девелопер.</div>
    </div>
    <button class="apc-ren-cta" onclick="alert('Форма появится здесь')">Хочу квартиру под ключ</button>
  </div></div>
</div>
</div>
  </div>
  <div class="apc-footer">
    <button class="apc-consult-btn" id="apc-consult-btn"><span class="apc-consult-btn-text">Получить консультацию</span></button>
  </div>
</div>

<!-- DESKTOP -->
<div class="desktop-filter-container hidden-mobile">
    <div class="filter-top-row">
        <div class="main-room-selector">{d_rooms}</div>
    </div>
    <div class="main-filters-row">
        <div class="main-filter-item"><div class="filter-label"><span>Площадь</span><span class="filter-values" id="d-area-val"></span></div><div id="d-slider-area"></div></div>
        <div class="main-filter-item"><div class="filter-label"><span>Цена</span><span class="filter-values" id="d-price-val"></span></div><div id="d-slider-price"></div></div>
    </div>
    <div class="main-towers-wrapper">
        <button class="district-btn" onclick="openMapPopup()">📍 Выбрать район</button>
    </div>
</div>

<!-- DESKTOP MODAL -->
<div class="desktop-filter-modal-overlay" id="desktop-filter-modal-overlay">
    <div class="desktop-filter-modal">
        <button class="desktop-modal-close" onclick="toggleDesktopFilterModal(false)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
        <div class="desktop-modal-title">Фильтры</div>
        <div class="desktop-modal-rooms">{d_rooms}</div>
        <div class="desktop-modal-sliders">
            <div class="desktop-modal-slider-item"><div class="filter-label"><span>Площадь</span><span class="filter-values" id="d-modal-area-val"></span></div><div id="d-modal-slider-area"></div></div>
            <div class="desktop-modal-slider-item"><div class="filter-label"><span>Цена</span><span class="filter-values" id="d-modal-price-val"></span></div><div id="d-modal-slider-price"></div></div>
        </div>
        <div class="desktop-modal-features">{dm_fin}</div>
        <button class="desktop-modal-apply" id="desktop-modal-apply-btn">Показать результаты</button>
    </div>
</div>

<div id="floating-filter-btn"><svg viewBox="0 0 24 24"><path d="M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z"/></svg><span>Фильтры</span></div>

<div id="mobile-top-bar">
  <div class="mtb-inner">
    <div class="mtb-icon-track">
      <button class="mtb-icon-btn" id="mtb-filter-btn" onclick="toggleMobileFilter(true)" title="Фильтры">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="3" y1="8" x2="21" y2="8"/><line x1="3" y1="16" x2="21" y2="16"/><circle cx="15" cy="8" r="2.2" fill="#fff" stroke="currentColor" stroke-width="1.8"/><circle cx="9" cy="16" r="2.2" fill="#fff" stroke="currentColor" stroke-width="1.8"/></svg>
      </button>
    </div>
    <div class="mtb-icon-track">
      <button class="mtb-icon-btn" id="mtb-sort-btn" onclick="openSortPopup()" title="Сортировка">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 4v16M8 4L5 7M8 4l3 3"/><path d="M16 20V4M16 20l-3-3M16 20l3-3"/></svg>
      </button>
    </div>
    <div class="mtb-center">
      <div class="mtb-count" id="mtb-count-text">Загрузка...</div>
    </div>
    <div class="mtb-icon-track" id="mtb-fav-track" style="position:relative">
      <button class="mtb-icon-btn" id="mtb-fav-btn" onclick="toggleFavPanel()" title="Избранное">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6-9 13-9 13z"/></svg>
      </button>
      <div class="mtb-fav-badge" id="mtb-fav-badge"></div>
    </div>
  </div>
</div>

<!-- SORT POPUP -->
<div id="sort-popup-overlay" onclick="closeSortPopup()"></div>
<div id="sort-popup">
  <div class="sort-popup-header">
    <div class="sort-popup-title">Сортировать варианты</div>
    <button class="sort-popup-close" onclick="closeSortPopup()">✕</button>
  </div>
  <div class="sort-popup-item" data-sort="price-asc" onclick="selectSort('price-asc')">
    <span class="sort-popup-item-label">Сначала дешевле</span>
    <div class="sort-popup-radio"></div>
  </div>
  <div class="sort-popup-item" data-sort="price-desc" onclick="selectSort('price-desc')">
    <span class="sort-popup-item-label">Сначала дороже</span>
    <div class="sort-popup-radio"></div>
  </div>
  <div class="sort-popup-item" data-sort="area-asc" onclick="selectSort('area-asc')">
    <span class="sort-popup-item-label">Сначала меньше по площади</span>
    <div class="sort-popup-radio"></div>
  </div>
  <div class="sort-popup-item" data-sort="area-desc" onclick="selectSort('area-desc')">
    <span class="sort-popup-item-label">Сначала больше по площади</span>
    <div class="sort-popup-radio"></div>
  </div>
</div>

<!-- MOBILE POPUP -->
<div class="filter-popup-overlay" id="mobile-filter-overlay"></div>
<div class="filter-popup" id="mobile-filter-popup">
    <div class="m-header"><div class="m-handle"></div><div class="m-title">Фильтры</div></div>
    <div class="m-back-btn" onclick="toggleMobileFilter(false)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg></div>
    <div class="m-content">
        <div class="m-block-spacer"><div class="m-section-label">Тип квартиры</div><div class="m-segment-track">{m_rooms}</div></div>
        <div class="m-block-spacer m-slider-styled">
            <div class="m-slider-row"><div class="m-slider-label-row"><span>Площадь</span></div><div id="m-slider-area"></div></div>
            <div class="m-slider-row"><div class="m-slider-label-row"><span>Цена</span></div><div id="m-slider-price"></div></div>
        </div>
        <!-- ОТДЕЛКА: скрыто, вернуть позже
        <div class="m-block-spacer"><div class="m-section-label">Отделка</div><div class="m-chips-track">{m_fin}</div></div>
        -->
        <div class="m-block-spacer">
            <button class="m-district-btn" onclick="openMapPopup()">Выбрать район</button>
        </div>
    </div>
    <div class="m-footer"><button class="m-apply-btn" id="m-apply-btn">Показать результаты</button></div>
</div>

<!-- INLINE MOBILE -->
<div class="inline-mobile-filter">
    <div class="m-block-spacer"><div class="m-section-label">Тип квартиры</div><div class="m-segment-track">{m_rooms}</div></div>
    <div class="m-block-spacer m-slider-styled">
        <div class="m-slider-row"><div class="m-slider-label-row"><span>Площадь</span></div><div id="m-inline-slider-area"></div></div>
        <div class="m-slider-row"><div class="m-slider-label-row"><span>Цена</span></div><div id="m-inline-slider-price"></div></div>
    </div>
    <!-- ОТДЕЛКА: скрыто, вернуть позже
    <div class="m-block-spacer"><div class="m-section-label">Отделка</div><div class="m-chips-track">{mi_fin}</div></div>
    -->
    <div class="m-block-spacer">
        <button class="m-district-btn" onclick="openMapPopup()">Выбрать район</button>
    </div>
</div>

<div class="qc-banner" id="qc-banner">
  <span class="qc-banner-text" id="qc-banner-text">Подборка</span>
  <button class="qc-banner-reset" onclick="resetQuickCategory()">← Все квартиры</button>
</div>
<div class="found-counter-wrapper">Найдено: <span class="count-num">0</span> вариантов</div>
<div class="apartments-grid" id="flats-container">{cards_html}</div>
<div class="load-more-wrapper"><button id="load-more-btn">Показать ещё</button></div>
<div id="no-results">Нет квартир по выбранным критериям</div>
</div>

<!-- MAP POPUP -->
<div class="map-popup-overlay" id="map-popup-overlay">
    <div class="map-popup" id="map-popup">
        <div class="map-popup-header">
            <div class="map-popup-title">Выберите район</div>
            <button class="map-popup-close" onclick="closeMapPopup()"><svg viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg></button>
        </div>
        <div class="map-svg-wrap">
            <div class="map-loading" id="map-loading">Загрузка...</div>
            <svg id="map-svg" viewBox="0 0 900 823" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%;display:block;opacity:0;transition:opacity 0.4s"></svg>
        </div>
        <svg class="map-compass" viewBox="0 0 36 36" width="36" height="36" xmlns="http://www.w3.org/2000/svg" style="position:absolute;top:14px;right:14px;z-index:10;pointer-events:none;width:47px;height:47px;flex:none">
            <circle cx="18" cy="18" r="17" fill="white" fill-opacity="0.92" stroke="#e0e0e0" stroke-width="1"/>
            <polygon points="18,5 21,18 18,15 15,18" fill="#C0392B"/>
            <polygon points="18,31 21,18 18,21 15,18" fill="#999"/>
            <text x="18" y="4" text-anchor="middle" font-size="5" font-family="Inter Tight,sans-serif" font-weight="600" fill="#C0392B" dominant-baseline="auto">N</text>
        </svg>
        <div class="map-bottom-panel">
            <div class="map-selected-bar" id="map-selected-bar">
                <div id="map-selected-chips" style="display:flex;gap:6px;flex-wrap:wrap;flex:1"></div>
                <button class="map-reset-btn" onclick="resetMapDistricts()">Сбросить</button>
            </div>
            <button class="map-apply-btn" id="map-apply-btn" onclick="applyMapDistricts()">Показать результаты</button>
        </div>
    </div>
</div>

<!-- noUiSlider загружается вместе с фильтром -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/noUiSlider/15.7.0/nouislider.min.js" defer></script>
<script src="{YANDEX_CLOUD_BASE_URL}/filter-data.js?v={BUILD_VERSION}" defer></script>
<script src="{YANDEX_CLOUD_BASE_URL}/filter.js?v={BUILD_VERSION}" defer></script>

    <div class="fav-panel-overlay" id="fav-panel-overlay" onclick="toggleFavPanel()"></div>
    <div class="fav-panel" id="fav-panel">
      <div class="fav-panel-header">
        <div style="display:flex;align-items:baseline;gap:8px">
          <span class="fav-panel-title">Избранное</span>
          <span class="fav-panel-count" id="fav-count"></span>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="fav-panel-sort-btn" onclick="shareFavourites()" title="Поделиться">
            <svg viewBox="0 0 24 24"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
          </button>
          <button class="fav-panel-sort-btn" id="fav-sort-btn" onclick="openFavSortPopup()" title="Сортировать">
            <svg viewBox="0 0 24 24"><path d="M8 4v16M8 4L5 7M8 4l3 3"/><path d="M16 20V4M16 20l-3-3M16 20l3-3"/></svg>
          </button>
          <button class="fav-panel-close" onclick="toggleFavPanel()">&#x2715;</button>
        </div>
      </div>
      <div class="fav-panel-list" id="fav-list">
        <div class="fav-panel-empty">Нет избранных квартир</div>
      </div>
    </div>
    <div class="fav-toast" id="fav-toast"><svg viewBox="0 0 24 24"><path d="M12 21C12 21 3 14 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6-9 13-9 13z"/></svg><span></span></div>

<!-- ═══════════════════════════ TG БЛОК ════════════════════════════ -->
<section style="background:#162138;padding:56px 24px 0;font-family:'Inter Tight',sans-serif;overflow:hidden;position:relative;padding-bottom:380px;">
  <div style="padding:0 0 40px;">
  <h2 style="font-size:clamp(26px,5vw,40px);font-weight:700;color:#fff;line-height:1.15;margin:0 0 32px;">Больше эксклюзивов<br>в нашем Telegram канале<br>и в MAX</h2>
  <ul style="list-style:none;padding:0;margin:0 0 40px;display:flex;flex-direction:column;gap:14px;">
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>закрытые старты, скидки и условия продаж
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>эксклюзивные планировки с разборами
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>мнения экспертов по дизайну, строительству и ремонту
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>обзоры проектов от бизнес до De Luxe класса
    </li>
  </ul>
  <div style="display:flex;flex-direction:column;gap:12px;max-width:360px;">
    <a href="https://t.me/royaltyplace_spb" style="display:flex;align-items:center;justify-content:center;gap:10px;background:#2AABEE;color:#fff;font-size:15px;font-weight:600;text-decoration:none;padding:16px 24px;border-radius:10px;">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248-2.04 9.607c-.15.666-.546.83-1.107.516l-3.07-2.263-1.48 1.423c-.164.164-.3.3-.616.3l.22-3.115 5.67-5.12c.247-.22-.054-.342-.383-.122L7.19 14.49l-3.01-.94c-.654-.204-.667-.654.137-.968l11.754-4.532c.545-.197 1.022.122.49.198z"/></svg>
      Перейти в Telegram-канал
    </a>
    <a href="https://max.ru/join/is7qpZrXePlRpIi1ClliKPk6EPhOB6iIFius8BrTQK8" style="display:flex;align-items:center;justify-content:center;gap:10px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.20);color:#fff;font-size:15px;font-weight:600;text-decoration:none;padding:16px 24px;border-radius:10px;">
      <img src="{YANDEX_CLOUD_BASE_URL}/background/Max_logo.svg" alt="MAX" style="width:20px;height:20px;filter:brightness(0) invert(1);">
      Перейти в MAX
    </a>
  </div>
  <div style="position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:420px;overflow:hidden;height:440px;z-index:2;">
    <img src="{YANDEX_CLOUD_BASE_URL}/background/terracebackgroundrp_terrace_.webp"
         alt="Royalty Place Telegram"
         loading="lazy"
         style="width:100%;display:block;object-fit:cover;object-position:center 10%;">
  </div>
</section>
<!-- ══════════════════════════════════════════════════════════════════ -->
</body>
</html>"""
    data_js = f"""const apartmentsData = {json_data};
const LIKES_URL = "{APPS_SCRIPT_LIKES_URL}";
const allRoomTypes   = {json_room_types};
const allFinishes    = {json_finishes};
const allDistricts   = {json_districts};
const sliderRanges   = {json_ranges};
window.sliderRanges = sliderRanges;
"""

    return html, css, js, data_js

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
_S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
_S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
_S3_BUCKET     = os.getenv("S3_BUCKET", "royaltyplace")
_S3_ENDPOINT   = os.getenv("S3_ENDPOINT", "https://storage.yandexcloud.net")

if not _S3_ACCESS_KEY or not _S3_SECRET_KEY:
    raise RuntimeError("❌ S3_ACCESS_KEY / S3_SECRET_KEY не найдены — проверь файл .env")

def _get_s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=_S3_ENDPOINT,
        aws_access_key_id=_S3_ACCESS_KEY,
        aws_secret_access_key=_S3_SECRET_KEY,
        region_name="ru-central1",
    )

def upload_to_s3(base_dir):
    """Загружает filter.css, filter.js, filter-data.js в Яндекс Object Storage."""
    try:
        import boto3
    except ImportError:
        print("⚠️  boto3 не установлен — пропускаю загрузку в S3")
        print("   Установи: pip install boto3")
        return

    # prefix из YANDEX_CLOUD_BASE_URL: https://storage.yandexcloud.net/royaltyplace/terrace → terrace
    prefix = YANDEX_CLOUD_BASE_URL.replace(f"{_S3_ENDPOINT}/{_S3_BUCKET}/", "").rstrip("/")

    # Стратегия кэширования:
    # index.html     — no-cache (данные квартир меняются при каждом запуске)
    # filter-data.js — no-cache (данные квартир)
    # filter.css     — 7 дней (меняется редко)
    # filter.js      — 7 дней (меняется редко)
    files = [
        ("index.html",     "text/html",              "no-cache, no-store, must-revalidate"),
        ("filter.css",     "text/css",               "public, max-age=604800"),
        ("filter.js",      "application/javascript", "public, max-age=604800"),
        ("filter-data.js", "application/javascript", "no-cache, no-store, must-revalidate"),
    ]

    try:
        s3 = _get_s3_client()
        print("\n☁️  Загрузка в S3...")
        for filename, content_type, cache_control in files:
            local_path = base_dir / filename
            if not local_path.exists():
                print(f"   ⚠️  {filename} не найден, пропускаю")
                continue
            key = f"{prefix}/{filename}"
            s3.upload_file(
                str(local_path),
                _S3_BUCKET,
                key,
                ExtraArgs={
                    "ContentType": f"{content_type}; charset=utf-8",
                    "CacheControl": cache_control,
                }
            )
            print(f"   ✅ {filename} → {_S3_ENDPOINT}/{_S3_BUCKET}/{key}")
        print("☁️  Загрузка завершена!")
    except Exception as e:
        print(f"⚠️  Ошибка загрузки в S3: {e}")


def generate_share_pages(apartments):
    """
    Генерирует мини HTML-страницы для шаринга каждой квартиры.
    Каждая страница содержит OG-теги (картинка, заголовок, описание)
    и мгновенно редиректит на основной сайт с ?apt=ID.
    Загружает в S3: terrace/share/{apt_id}.html
    Умная логика: заливает только новые или изменившиеся страницы.
    """
    try:
        import boto3
    except ImportError:
        print("⚠️  boto3 не установлен — пропускаю генерацию share-страниц")
        return

    try:
        s3 = _get_s3_client()
    except Exception as e:
        print(f"⚠️  S3 недоступен для share-страниц: {e}")
        return

    prefix = YANDEX_CLOUD_BASE_URL.replace(f"https://storage.yandexcloud.net/{_S3_BUCKET}/", "").rstrip("/")
    share_prefix = f"{prefix}/share/"

    # Получаем список уже загруженных страниц из S3
    existing = set()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=share_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                apt_id = key.replace(share_prefix, "").replace(".html", "")
                existing.add(apt_id)
        print(f"\n🔗 Share-страниц в S3: {len(existing)} шт.")
    except Exception as e:
        print(f"  ⚠️  Не удалось получить список из S3: {e}")

    # Определяем что заливать:
    # - новые квартиры (нет в S3)
    # - квартиры у которых появилась картинка (img не пустой, а страница уже есть — перезальём)
    to_upload = []
    for apt in apartments:
        apt_id  = apt["id"]
        has_img = bool(apt.get("img", ""))
        if apt_id not in existing:
            to_upload.append((apt, "новая"))
        elif has_img:
            # Перезаливаем только если есть картинка — вдруг раньше её не было
            to_upload.append((apt, "обновление"))

    # Убираем дубли обновлений — если уже есть и картинка не изменилась не трогаем
    # Для этого используем простой хэш из img+price
    import hashlib
    CACHE_FILE = BASE_DIR / ".share_cache.json"
    cache = {}
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    final_upload = []
    for apt, reason in to_upload:
        apt_id   = apt["id"]
        img      = apt.get("img", "")
        price    = apt.get("ps", "")
        checksum = hashlib.md5(f"{img}{price}".encode()).hexdigest()[:8]
        if reason == "обновление" and cache.get(apt_id) == checksum:
            continue  # не изменилось — пропускаем
        final_upload.append((apt, reason, checksum))

    if not final_upload:
        print(f"   ✅ Все share-страницы актуальны — ничего не нужно заливать")
        return

    print(f"   📤 Заливаем: {len(final_upload)} шт. "
          f"(новых: {sum(1 for _,r,_ in final_upload if r=='новая')}, "
          f"обновлений: {sum(1 for _,r,_ in final_upload if r=='обновление')})")

    uploaded = 0
    for apt, reason, checksum in final_upload:
        apt_id   = apt["id"]
        apt_url  = f"{MAIN_SITE_URL}/?apt={apt_id}"
        img_url  = apt.get("img", "")

        # Заголовок: "3 комнаты, 90.78 м² · Петроградский"
        parts = [apt.get("rd", "Квартира")]
        if apt.get("a"): parts[0] += f", {apt['a']} м²"
        if apt.get("district"): parts.append(apt["district"])
        og_title = " · ".join(parts)

        # Описание: цена + этаж + отделка + срок
        desc_parts = []
        if apt.get("ps"):      desc_parts.append(f"Цена: {apt['ps']}")
        if apt.get("f"):       desc_parts.append(f"Этаж {apt['f']}")
        if apt.get("finish"):  desc_parts.append(apt["finish"])
        if apt.get("deadline"):desc_parts.append(f"Сдача: {apt['deadline']}")
        og_desc = " · ".join(desc_parts) if desc_parts else "Квартиры с террасами · Санкт-Петербург"

        og_image_tag = (f'<meta property="og:image" content="{img_url}">\n'
                        f'  <meta property="og:image:width" content="800">\n'
                        f'  <meta property="og:image:height" content="800">') if img_url else ""
        tw_image_tag = f'<meta name="twitter:image" content="{img_url}">' if img_url else ""

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta property="og:type"        content="website">
  <meta property="og:site_name"   content="Квартиры с террасами · Санкт-Петербург">
  <meta property="og:url"         content="{apt_url}">
  <meta property="og:title"       content="{og_title}">
  <meta property="og:description" content="{og_desc}">
  {og_image_tag}
  <meta name="twitter:card"        content="summary_large_image">
  <meta name="twitter:title"       content="{og_title}">
  <meta name="twitter:description" content="{og_desc}">
  {tw_image_tag}
  <meta http-equiv="refresh" content="0;url={apt_url}">
</head>
<body>
  <script>window.location.replace("{apt_url}");</script>
  <a href="{apt_url}">{og_title}</a>

<!-- ═══════════════════════════ TG БЛОК ════════════════════════════ -->
<section style="background:#162138;padding:56px 24px 0;font-family:'Inter Tight',sans-serif;overflow:hidden;position:relative;padding-bottom:380px;">
  <div style="padding:0 0 40px;">
  <h2 style="font-size:clamp(26px,5vw,40px);font-weight:700;color:#fff;line-height:1.15;margin:0 0 32px;">Больше эксклюзивов<br>в нашем Telegram канале<br>и в MAX</h2>
  <ul style="list-style:none;padding:0;margin:0 0 40px;display:flex;flex-direction:column;gap:14px;">
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>закрытые старты, скидки и условия продаж
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>эксклюзивные планировки с разборами
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>мнения экспертов по дизайну, строительству и ремонту
    </li>
    <li style="display:flex;align-items:flex-start;gap:12px;color:rgba(255,255,255,.80);font-size:15px;line-height:1.5;">
      <span style="color:#CBA363;flex-shrink:0;margin-top:2px;">—</span>обзоры проектов от бизнес до De Luxe класса
    </li>
  </ul>
  <div style="display:flex;flex-direction:column;gap:12px;max-width:360px;">
    <a href="https://t.me/royaltyplace_spb" style="display:flex;align-items:center;justify-content:center;gap:10px;background:#2AABEE;color:#fff;font-size:15px;font-weight:600;text-decoration:none;padding:16px 24px;border-radius:10px;">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248-2.04 9.607c-.15.666-.546.83-1.107.516l-3.07-2.263-1.48 1.423c-.164.164-.3.3-.616.3l.22-3.115 5.67-5.12c.247-.22-.054-.342-.383-.122L7.19 14.49l-3.01-.94c-.654-.204-.667-.654.137-.968l11.754-4.532c.545-.197 1.022.122.49.198z"/></svg>
      Перейти в Telegram-канал
    </a>
    <a href="https://max.ru/join/is7qpZrXePlRpIi1ClliKPk6EPhOB6iIFius8BrTQK8" style="display:flex;align-items:center;justify-content:center;gap:10px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.20);color:#fff;font-size:15px;font-weight:600;text-decoration:none;padding:16px 24px;border-radius:10px;">
      <img src="{YANDEX_CLOUD_BASE_URL}/background/Max_logo.svg" alt="MAX" style="width:20px;height:20px;filter:brightness(0) invert(1);">
      Перейти в MAX
    </a>
  </div>
  <div style="position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:420px;overflow:hidden;height:440px;z-index:2;">
    <img src="{YANDEX_CLOUD_BASE_URL}/background/terracebackgroundrp_terrace_.webp"
         alt="Royalty Place Telegram"
         loading="lazy"
         style="width:100%;display:block;object-fit:cover;object-position:center 10%;">
  </div>
</section>
<!-- ══════════════════════════════════════════════════════════════════ -->
</body>
</html>"""

        key = f"{share_prefix}{apt_id}.html"
        try:
            s3.put_object(
                Bucket=_S3_BUCKET,
                Key=key,
                Body=html.encode("utf-8"),
                ContentType="text/html; charset=utf-8",
                CacheControl="no-cache",
            )
            cache[apt_id] = checksum
            uploaded += 1
        except Exception as e:
            print(f"  ⚠️  {apt_id}: {e}")

    # Сохраняем кэш
    try:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    print(f"   ✅ Share-страниц загружено: {uploaded}")


def main():
    print("🚀 Генератор фильтра TrendAgent\n")
    excel_path  = find_latest_excel()
    layouts_dir = find_latest_layouts()

    apartments, room_types, finishes, districts, ranges = load_data(excel_path, layouts_dir)
    if not apartments:
        print("❌ Нет данных для генерации")
        return

    html, css, js, data_js = generate_html(apartments, room_types, finishes, districts, ranges)

    # Подставляем версию шаринга — увеличивай SHARE_VERSION чтобы сбросить кэш Telegram
    js = js.replace('SHARE_VERSION_PLACEHOLDER', str(SHARE_VERSION))

    OUTPUT_FILE.write_text(html, encoding='utf-8')
    (BASE_DIR / "filter.css").write_text(css, encoding='utf-8')
    (BASE_DIR / "filter.js").write_text(js,  encoding='utf-8')
    (BASE_DIR / "filter-data.js").write_text(data_js, encoding='utf-8')

    # ── Загрузка в Яндекс S3 ──────────────────────────────────
    upload_to_s3(BASE_DIR)
    generate_share_pages(apartments)

    print(f"\n🎉 Готово! Созданы файлы:")
    print(f"   📄 {OUTPUT_FILE.name}           → загрузи в Тильду (HTML-блок)")
    print(f"   🎨 filter.css                  → загрузи в Яндекс Object Storage")
    print(f"   ⚙️  filter.js                   → загрузи в Яндекс Object Storage")
    print(f"   📦 filter-data.js              → загрузи в Яндекс Object Storage")
    print(f"\n   Проверь YANDEX_CLOUD_BASE_URL в начале скрипта: {YANDEX_CLOUD_BASE_URL}")
    print(f"\n   ⚠️  Переименуйте папку layouts_* → layouts/  рядом с index.html")

if __name__ == '__main__':
    main()

# --- Автосинк в git-репо ---
try:
    from git_sync import git_sync
    git_sync("generator run")
except Exception as e:
    print(f"git_sync skipped: {e}")
