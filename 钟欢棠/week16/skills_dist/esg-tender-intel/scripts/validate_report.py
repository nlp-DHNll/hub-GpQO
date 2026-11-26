#!/usr/bin/env python3
"""Deterministic final-report validation: structure, sourcing, dates, placeholders."""

import argparse
import json
import os
import re
from datetime import date, datetime


def parse_date(text):
    m = re.search(r'(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})', text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description='Validate a generated ESG report.')
    parser.add_argument('--report', required=True)
    parser.add_argument('--type', choices=['monthly', 'tender'], required=True)
    parser.add_argument('--min-sources', type=int, default=8)
    parser.add_argument('--window-start')
    parser.add_argument('--window-end')
    parser.add_argument('--evidence', help='Evidence JSON to cross-check cited URLs.')
    parser.add_argument('--out', help='Optional validation JSON path.')
    args = parser.parse_args()

    with open(args.report, encoding='utf-8') as handle:
        text = handle.read()
    issues = []
    checks = {}

    checks['non_empty'] = len(text) >= 1500
    if not checks['non_empty']:
        issues.append('报告过短（<1500字符）')

    required = (['政策', '评级', '标准', '行业', '建议', '来源']
                if args.type == 'monthly' else ['中标', '金额', '热点', '监控', '来源'])
    for keyword in required:
        ok = keyword in text
        checks['section_' + keyword] = ok
        if not ok:
            issues.append('缺少必要章节关键词：' + keyword)

    urls = re.findall(r'https?://[^\s)\]】>]+', text)
    checks['source_count'] = len(urls) >= args.min_sources
    if not checks['source_count']:
        issues.append('可核验链接少于 {} 个（实际 {}）'.format(args.min_sources, len(urls)))

    window_dates = [parse_date(m) for m in re.findall(r'20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}', text)]
    window_dates = [d for d in window_dates if d]
    if args.window_start and args.window_end:
        start, end = date.fromisoformat(args.window_start), date.fromisoformat(args.window_end)
        in_window = [d for d in window_dates if start <= d <= end]
        checks['dates_in_window'] = len(in_window) >= 3
        if not checks['dates_in_window']:
            issues.append('时间窗内的明确日期少于3个')

    placeholders = [p for p in ['TODO', 'TBD', '待补充', 'XXX', '示例数据', 'lorem']
                    if p in text]
    checks['no_placeholders'] = not placeholders
    if placeholders:
        issues.append('存在占位符：' + ', '.join(placeholders))

    numeric_claims = re.findall(r'\d+(?:\.\d+)?\s*(?:亿元|万元|%|％|家|项)', text)
    checks['numeric_evidence'] = len(numeric_claims) >= 5
    if not checks['numeric_evidence']:
        issues.append('关键数字不足5处')

    if args.evidence:
        with open(args.evidence, encoding='utf-8') as handle:
            evidence = json.load(handle)
        evidence_urls = {i.get('url') for i in evidence.get('items', [])}
        matched = sum(1 for u in urls if u.rstrip('.,；。') in evidence_urls)
        checks['evidence_crosscheck'] = matched >= min(3, args.min_sources)
        if not checks['evidence_crosscheck']:
            issues.append('报告中引用证据池URL不足：{} / {}'.format(matched, min(3, args.min_sources)))

    hard_fails = ['non_empty', 'no_placeholders', 'source_count', 'section_来源']
    score = 100 - 12 * len(issues)
    score = max(0, score)
    result = {
        'report': args.report,
        'type': args.type,
        'validated_at': datetime.now().isoformat(timespec='seconds'),
        'score': score,
        'passed': all(checks.get(k, False) for k in hard_fails) and score >= 60,
        'checks': checks,
        'issues': issues,
        'stats': {'characters': len(text), 'urls': len(urls), 'dates': len(window_dates),
                  'numeric_claims': len(numeric_claims)},
    }
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    print('VALIDATION score={} passed={} issues={}'.format(score, result['passed'], len(issues)))
    for issue in issues:
        print('  -', issue)
    if not result['passed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
