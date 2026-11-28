#!/usr/bin/env python3
"""Deterministic page fetching and extractive summarization.

No LLM: fetches top-ranked search hits, strips HTML, scores sentences with
jieba TF-IDF weights plus a position prior, extracts key phrases and numeric
facts, and emits a structured evidence JSON (and optional Markdown table).
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime
from html.parser import HTMLParser

import requests

import jieba
import jieba.analyse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
SKIP_TAGS = {'script', 'style', 'noscript', 'svg', 'iframe', 'nav', 'footer', 'header', 'form'}
BLOCK_TAGS = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'section'}
NUMBER_RE = re.compile(r'\d[\d,.]*\s*(?:亿元|万元|亿千瓦|万吨|亿吨|兆瓦|千瓦|%|％|吨|人|家|项|年)')


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        elif tag in BLOCK_TAGS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        raw = html.unescape(''.join(self.parts))
        lines = []
        for line in raw.split('\n'):
            line = re.sub(r'\s+', ' ', line).strip()
            if len(line) >= 12 and re.search(r'[\u4e00-\u9fff]', line):
                lines.append(line)
        return '\n'.join(lines)


def clean_text(raw):
    noise = ['点击上方', '扫码关注', '版权归原作者', '责任编辑', '来源:', '来源：', '广告', '相关推荐']
    lines = []
    for line in raw.split('\n'):
        if any(n in line for n in noise):
            continue
        digit_ratio = sum(ch.isdigit() for ch in line) / max(1, len(line))
        if digit_ratio > 0.25 or line.count('%') > 3:
            continue
        lines.append(line)
    return '\n'.join(lines)


def fetch_page(url, timeout):
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        parser = TextExtractor()
        parser.feed(response.text)
        return clean_text(parser.text()), 'ok'
    except Exception as exc:
        return '', 'error:{}'.format(type(exc).__name__)


def split_sentences(text):
    return [s.strip() for s in re.split(r'[。！？!?；;\n]+', text) if len(s.strip()) >= 12]


def summarize_text(title, text, max_sentences=3):
    source_text = text if text else title
    sentences = split_sentences(source_text)
    if not sentences:
        source_text = title
        sentences = split_sentences(source_text)
    if not sentences:
        return [], [], []
    keywords = jieba.analyse.extract_tags(source_text, topK=20, withWeight=True)
    weights = dict(keywords)
    scored = []
    for idx, sentence in enumerate(sentences):
        words = [w for w in jieba.cut(sentence) if len(w) > 1]
        score = sum(weights.get(w, 0.0) for w in words) / (len(words) ** 0.5 + 1)
        if idx < 2:
            score *= 1.25
        scored.append((idx, sentence, round(score, 4)))
    best = sorted(scored, key=lambda x: (-x[2], x[0]))[:max_sentences]
    best_sorted = sorted(best, key=lambda x: x[0])
    return [s for _, s, _ in best_sorted], [w for w, _ in keywords[:12]], NUMBER_RE.findall(source_text)[:10]


def main():
    parser = argparse.ArgumentParser(description='Deterministic extractive summarizer.')
    parser.add_argument('--input', required=True, help='JSON written by search_web.py.')
    parser.add_argument('--out', required=True, help='Output evidence JSON.')
    parser.add_argument('--out-md', help='Optional Markdown evidence table.')
    parser.add_argument('--limit', type=int, default=30, help='Max items to process.')
    parser.add_argument('--fetch-limit', type=int, default=12, help='Max pages to fetch in full.')
    parser.add_argument('--timeout', type=int, default=8)
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as handle:
        payload = json.load(handle)
    items = payload['items'][:args.limit]
    results = []
    fetched = 0
    for rank, item in enumerate(items):
        page_text, status = '', 'snippet-only'
        if rank < args.fetch_limit:
            page_text, status = fetch_page(item['url'], args.timeout)
            if status == 'ok':
                fetched += 1
        text = page_text if page_text else item.get('snippet', '')
        summary, keywords, numbers = summarize_text(item['title'], text)
        results.append({
            'rank': rank + 1,
            'id': item['id'],
            'title': item['title'],
            'url': item['url'],
            'date': item.get('date'),
            'source': item.get('source', ''),
            'search_score': item.get('score', 0),
            'fetch_status': status,
            'characters': len(text),
            'keywords': keywords,
            'key_numbers': numbers,
            'summary': summary,
        })

    payload_out = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'input_file': args.input,
        'items_processed': len(results),
        'pages_fetched_ok': fetched,
        'method': 'jieba TF-IDF sentence scoring + position prior (extractive, no LLM)',
        'items': results,
    }
    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(payload_out, handle, ensure_ascii=False, indent=2)

    if args.out_md:
        lines = ['| # | 日期 | 来源 | 标题 | 关键句（抽取式） | 关键数字 |',
                 '|---|------|------|------|------------------|----------|']
        for it in results:
            title = it['title'].replace('|', '/')
            summ = ' '.join(it['summary']).replace('|', '/')[:180]
            nums = ', '.join(it['key_numbers'][:6]).replace('|', '/')
            lines.append('| {} | {} | {} | [{}]({}) | {} | {} |'.format(
                it['rank'], it['date'] or '-', it['source'], title, it['url'], summ, nums))
        with open(args.out_md, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
    print('WROTE {} items={} fetched_ok={}'.format(args.out, len(results), fetched))


if __name__ == '__main__':
    main()
