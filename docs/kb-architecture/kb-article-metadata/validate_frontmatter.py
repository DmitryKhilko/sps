#!/usr/bin/env python3
"""Проверка frontmatter в Markdown-файлах базы знаний.

Использование:
    python validate_frontmatter.py PATH [PATH ...] [--schema frontmatter.schema.json] [--taxonomy taxonomy.yml]

PATH - файл .md или каталог (обход рекурсивный). Код возврата 1, если найдены ошибки.
Зависимости: pip install pyyaml jsonschema
"""
import argparse
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

# Поля, значения которых проверяются по справочнику: поле -> ключ в taxonomy.yml
TAXONOMY_FIELDS = {
    "status": "status", "doc_type": "doc_type", "department": "department",
    "topic": "topic", "product": "product", "audience": "audience",
    "region": "region", "sensitivity_level": "sensitivity_level",
    "language": "language",
}
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
DATE_FIELDS = ["date_published", "last_updated", "review_date", "valid_until"]


def parse_date(value):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def check_file(path, validator, taxonomy):
    errors = []
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, ["frontmatter не найден: файл должен начинаться со строки '---'"]
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        return None, [f"некорректный YAML: {e}"]
    if not isinstance(meta, dict):
        return None, ["frontmatter должен быть набором пар «ключ: значение»"]
    body = m.group(2)

    # 1. Структура и типы (даты без кавычек YAML превращает в тип date - это ошибка типа)
    for err in sorted(validator.iter_errors(meta), key=lambda e: list(e.path)):
        where = ".".join(str(p) for p in err.path) or "(корень)"
        errors.append(f"схема [{where}]: {err.message}")

    # 2. Справочники
    for field, key in TAXONOMY_FIELDS.items():
        value = meta.get(field)
        if isinstance(value, str) and value not in taxonomy.get(key, []):
            errors.append(f"справочник [{field}]: значение '{value}' отсутствует в taxonomy.yml ({key})")
    tags = meta.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if tag not in taxonomy.get("tags", []):
                errors.append(f"справочник [tags]: тег '{tag}' отсутствует в taxonomy.yml")

    # 3. title == H1
    h1 = H1_RE.search(body)
    if not h1:
        errors.append("в файле нет заголовка H1")
    elif meta.get("title") != h1.group(1):
        errors.append(f"title не совпадает с H1: '{meta.get('title')}' != '{h1.group(1)}'")

    # 6. Даты
    dates = {}
    for f in DATE_FIELDS:
        if f in meta:
            d = parse_date(meta[f])
            if d is None and isinstance(meta[f], str):
                errors.append(f"даты [{f}]: '{meta[f]}' - несуществующая дата")
            dates[f] = d
    lu, dp, rd = dates.get("last_updated"), dates.get("date_published"), dates.get("review_date")
    if dp and lu and dp > lu:
        errors.append("даты: date_published позже last_updated")
    if rd and lu and rd < lu:
        errors.append("даты: review_date раньше last_updated")

    # 7. Жизненный цикл
    if meta.get("status") == "archived" and not meta.get("replaced_by"):
        errors.append("жизненный цикл: для status 'archived' укажите replaced_by")

    # 8. Безопасность
    if meta.get("sensitivity_level") in ("confidential", "restricted"):
        broad = set(taxonomy.get("broad_groups", []))
        used = broad.intersection(meta.get("allowed_groups") or [])
        if used:
            errors.append(f"безопасность: общие группы {sorted(used)} недопустимы для "
                          f"sensitivity_level '{meta['sensitivity_level']}'")
    return meta, errors


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--schema", default=str(here / "frontmatter.schema.json"))
    ap.add_argument("--taxonomy", default=str(here / "taxonomy.yml"))
    args = ap.parse_args()

    import json
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    taxonomy = yaml.safe_load(Path(args.taxonomy).read_text(encoding="utf-8"))

    files = []
    for p in map(Path, args.paths):
        files.extend(sorted(p.rglob("*.md")) if p.is_dir() else [p])

    failed = 0
    ids = defaultdict(list)
    all_meta = {}
    for f in files:
        meta, errors = check_file(f, validator, taxonomy)
        if meta and isinstance(meta.get("document_id"), str):
            ids[meta["document_id"]].append(f)
            all_meta[f] = meta
        if errors:
            failed += 1
            print(f"\n{f}")
            for e in errors:
                print(f"  - {e}")

    # 5. Уникальность document_id и существование ссылок (на уровне всей базы)
    base_errors = []
    for doc_id, fs in ids.items():
        if len(fs) > 1:
            base_errors.append(f"document_id {doc_id} повторяется: {', '.join(map(str, fs))}")
    for f, meta in all_meta.items():
        refs = list(meta.get("related") or [])
        for key in ("replaced_by", "supersedes"):
            if meta.get(key):
                refs.append(meta[key])
        for ref in refs:
            if ref not in ids:
                base_errors.append(f"{f}: ссылка на несуществующий document_id {ref}")
    if base_errors:
        failed += 1
        print("\nПроверки на уровне базы:")
        for e in base_errors:
            print(f"  - {e}")

    print(f"\nПроверено файлов: {len(files)}; с ошибками: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
