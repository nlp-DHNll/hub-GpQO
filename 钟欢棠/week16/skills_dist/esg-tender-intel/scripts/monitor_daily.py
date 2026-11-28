#!/usr/bin/env python3
"""Deterministic daily tender monitor with incremental state.

Compares today's search results against a persisted seen-ID set, emits only
new ESG-related tenders as a Markdown digest, then updates the state file.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime


def item_id(item):
    key = item.get('url') or item.get('title', '')
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]


def main():
    parser = argparse.ArgumentParser(description=' Daily ESG tender monitor.')
    parser.add_argument('--input', required=True, help='Today\'s search/evidence JSON.')
    parser.add_argument('--state', required=True, help='Persisted JSON state file.')
    parser.add_argument('--out', required=True, help='Output Markdown digest path.')
    parser.add_argument('--date', default=datetime.now().date().isoformat())
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as handle:
        payload = json.load(handle)
    state = {'last_run': '', 'seen_ids': []}
    if os.path.exists(args.state):
        try:
            with open(args.state, encoding='utf-8') as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            pass
    known = set(state.get('seen_ids', []))

    new_items = []
    for item in payload.get('items', []):
        iid = item_id(item)
        if iid in known:
            continue
        known.add(iid)
        new_items.append({
            'id': iid,
            'title': item.get('title', ''),
            'url': item.get('url', ''),
            'date': item.get('date') or args.date,
            'source': item.get('source', ''),
            'snippet': (item.get('snippet') or ' '.join(item.get('summary', [])))[:220],
        })
    new_items.sort(key=lambda x: (x['date'], x['title']), reverse=True)
    new_items = new_items[:args.limit]

    lines = ['# ESG相关招标信息每日推送 — {}'.format(args.date), '',
             '本次扫描 {} 条，新增 {} 条。'.format(len(payload.get('items', [])), len(new_items)), '']
    if new_items:
        lines += ['| 日期 | 来源 | 项目/公告 | 摘要 | 链接 |',
                  '|------|------|-----------|------|------|']
        for item in new_items:
            lines.append('| {} | {} | {} | {} | [查看]({}) |'.format(
                item['date'], item['source'], item['title'].replace('|', '/'),
                item['snippet'].replace('|', '/').replace('\n', ' '), item['url']))
    else:
        lines.append('今日无新增ESG相关招标信息。')
    lines += ['', '> 生成方式：确定性脚本去重比对（URL SHA1），无LLM改写。']

    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')

    state['last_run'] = args.date
    state['seen_ids'] = sorted(known)[-5000:]
    os.makedirs(os.path.dirname(os.path.abspath(args.state)), exist_ok=True)
    with open(args.state, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    print('WROTE {} new={} known={}'.format(args.out, len(new_items), len(known)))


if __name__ == '__main__':
    main()
