#!/usr/bin/env python3
"""Deterministic ESG tender extraction, normalization and statistics.

Reads a search/evidence JSON, extracts winner, amount, date and theme for each
bidding record with fixed regex rules, normalizes all amounts to 万元, removes
duplicates, and writes structured CSV/JSON/Markdown statistical outputs.
No LLM reasoning is used in this stage.
"""

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

THEME_RULES = [
    ('双碳与碳管理', ['双碳', '碳达峰', '碳中和', '碳管理', '碳核算', '碳排放', '碳盘查', '碳资产', '碳账户', 'CCER', '碳足迹']),
    ('ESG评价与咨询', ['ESG', 'esg', '可持续发展', '社会责任', '绿色金融', 'ESG报告']),
    ('节能与能源托管', ['能源托管', '节能降碳', '合同能源管理', '节能改造', '节能服务', '能耗']),
    ('绿色建筑与低碳园区', ['绿色建筑', '低碳园区', '超低能耗', '零碳园区', '绿色园区', '海绵城市']),
    ('清洁能源与新能源', ['光伏', '风电', '新能源', '储能', '绿电', '氢能']),
    ('碳市场与绿色认证', ['碳交易', '绿色认证', '碳抵消', '碳中和评价', ' CDM ', '绿证']),
]
AMOUNT_PATTERNS = [
    re.compile(r'(?:含税(?:人民币)?|中标(?:成交)?金额|报价总金额|成交金额|中标金额)[^\d]{0,12}([\d,]+(?:\.\d+)?)\s*(亿元|万元|元)'),
    re.compile(r'([\d,]+(?:\.\d+)?)\s*(亿元|万元)(?=[^。；]{0,20}(?:中标|成交|金额))'),
]
SUPPLIER_PATTERNS = [
    re.compile(r'(?:中标(?:成交)?(?:人|单位|供应商)?名称|中选人名称|中标单位|中选单位|成交供应商)\s*[:：]?\s*([\u4e00-\u9fffA-Za-z0-9（）()·]{3,40})'),
]
PROJECT_NO_RE = re.compile(r'项目编号\s*[:：]\s*([A-Za-z0-9\-（）()]+)')
DATE_RE = re.compile(r'(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})')
SHORT_DATE_RE = re.compile(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日')


def to_wan(number, unit):
    value = float(number.replace(',', ''))
    return round(value * 10000 if unit == '亿元' else (value / 10000 if unit == '元' else value), 4)


def extract_amount(text):
    candidates = []
    for pattern in AMOUNT_PATTERNS:
        for m in pattern.finditer(text):
            value = to_wan(m.group(1), m.group(2))
            if 0.01 <= value <= 5_000_000:
                priority = 2 if '含税' in text[max(0, m.start() - 12):m.start()] else 1
                candidates.append((priority, value))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][1]


def extract_supplier(text):
    for pattern in SUPPLIER_PATTERNS:
        m = pattern.search(text)
        if m:
            return re.sub(r'\s+', '', m.group(1))[:40]
    return ''


def extract_date(text, reference_date):
    if isinstance(reference_date, str):
        reference_date = datetime.fromisoformat(reference_date).date()
    m = DATE_RE.search(text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
        except ValueError:
            pass
    m = SHORT_DATE_RE.search(text)
    if m:
        try:
            return datetime(reference_date.year, int(m.group(1)), int(m.group(2))).date().isoformat()
        except ValueError:
            pass
    return ''


def classify(text):
    tags = [name for name, words in THEME_RULES if any(w in text for w in words)]
    return tags[0] if tags else '其他相关', tags


def normalize_key(title):
    return re.sub(r'[\s\W_]+', '', title).lower()[:60]


def text_of(item):
    parts = [item.get('title', '')]
    if item.get('snippet'):
        parts.append(item['snippet'])
    if item.get('summary'):
        parts.append(''.join(item['summary']) if isinstance(item['summary'], list) else item['summary'])
    return ' '.join(str(p) for p in parts)


def amount_bin(wan):
    if wan is None:
        return '未披露'
    if wan < 10:
        return '10万元以下'
    if wan < 100:
        return '10万-100万元'
    if wan < 1000:
        return '100万-1000万元'
    if wan < 10000:
        return '1000万-1亿元'
    return '1亿元以上'


def main():
    parser = argparse.ArgumentParser(description='Aggregate ESG tender results deterministically.')
    parser.add_argument('--input', required=True, help='JSON from search_web.py or summarize.py.')
    parser.add_argument('--out-json', required=True)
    parser.add_argument('--out-csv', required=True)
    parser.add_argument('--out-md', required=True)
    parser.add_argument('--reference-date', default=datetime.now().date().isoformat())
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as handle:
        payload = json.load(handle)
    records, seen = [], set()
    for item in payload.get('items', []):
        text = text_of(item)
        title = item.get('title', '').strip()
        if not title:
            continue
        key = normalize_key(title)
        project_no = PROJECT_NO_RE.search(text)
        if project_no:
            key = project_no.group(1)
        if key in seen:
            continue
        seen.add(key)
        theme, tags = classify(text)
        amount = extract_amount(text)
        records.append({
            'project': title,
            'project_no': project_no.group(1) if project_no else '',
            'date': extract_date(text, args.reference_date),
            'source': item.get('source', ''),
            'url': item.get('url', ''),
            'supplier': extract_supplier(text),
            'amount_wan': amount,
            'amount_bin': amount_bin(amount),
            'theme': theme,
            'tags': tags,
        })

    theme_stat = defaultdict(lambda: {'count': 0, 'sum_wan': 0.0, '披露数': 0})
    month_stat, supplier_stat, bin_stat = Counter(), Counter(), Counter()
    for rec in records:
        theme_stat[rec['theme']]['count'] += 1
        if rec['amount_wan'] is not None:
            theme_stat[rec['theme']]['sum_wan'] += rec['amount_wan']
            theme_stat[rec['theme']]['披露数'] += 1
        month_stat[rec['date'][:7] or '未知'] += 1
        bin_stat[rec['amount_bin']] += 1
        if rec['supplier']:
            supplier_stat[rec['supplier']] += 1
    for stat in theme_stat.values():
        stat['sum_wan'] = round(stat['sum_wan'], 2)

    ranked = sorted([r for r in records if r['amount_wan'] is not None],
                    key=lambda r: -r['amount_wan'])[:10]
    output = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'input_file': args.input,
        'reference_date': args.reference_date,
        'record_count': len(records),
        'disclosed_count': len(ranked) if len(ranked) <= 10 else sum(1 for r in records if r['amount_wan'] is not None),
        'disclosed_amount_wan': round(sum(r['amount_wan'] for r in records if r['amount_wan'] is not None), 2),
        'method': 'regex extraction + rule-based theme/amount normalization; no LLM',
        'statistics': {
            'by_theme': dict(theme_stat),
            'by_month': dict(sorted(month_stat.items())),
            'by_amount_bin': dict(bin_stat),
            'top_suppliers': dict(supplier_stat.most_common(10)),
        },
        'top_records': ranked,
        'records': records,
    }

    parent = os.path.dirname(os.path.abspath(args.out_json))
    os.makedirs(parent, exist_ok=True)
    with open(args.out_json, 'w', encoding='utf-8') as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    with open(args.out_csv, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()) if records else ['project'])
        writer.writeheader()
        writer.writerows(records)

    lines = ['# ESG招投标确定性汇总结果', '',
             '记录数：{}；披露金额记录：{}；披露金额合计：{} 万元'.format(
                 output['record_count'],
                 sum(1 for r in records if r['amount_wan'] is not None),
                 output['disclosed_amount_wan']), '',
             '## 主题分布', '', '| 主题 | 记录数 | 披露金额记录 | 金额合计（万元） |',
             '|------|--------|--------------|------------------|']
    for theme, stat in sorted(theme_stat.items(), key=lambda x: -x[1]['sum_wan']):
        lines.append('| {} | {} | {} | {} |'.format(theme, stat['count'], stat['披露数'], stat['sum_wan']))
    lines += ['', '## 金额区间分布', '', '| 区间 | 数量 |', '|------|------|']
    for key, count in sorted(bin_stat.items()):
        lines.append('| {} | {} |'.format(key, count))
    lines += ['', '## 金额 TOP10', '', '| 项目 | 中标单位 | 金额（万元） | 日期 | 主题 | 链接 |',
              '|------|----------|--------------|------|------|------|']
    for rec in ranked:
        lines.append('| {} | {} | {} | {} | {} | {} |'.format(
            rec['project'].replace('|', '/'), rec['supplier'], rec['amount_wan'],
            rec['date'], rec['theme'], rec['url']))
    with open(args.out_md, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('WROTE {} records={}'.format(args.out_json, len(records)))


if __name__ == '__main__':
    main()
