#!/usr/bin/env python3
"""Deterministic web-search collector for ESG research.

Primary backend: 360 search HTML (stable for Chinese queries in this
environment, exposes the true target URL in data-mdurl). Fallback: Bing HTML.
Fixed parsing rules + date inference + dedup + authority/recency/keyword
scoring. No LLM calls: for a frozen snapshot of the web, output is reproducible.
"""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

AUTHORITY = {
    "gov.cn": 10, "ccgp.gov.cn": 10, "ndrc.gov.cn": 9, "mee.gov.cn": 9,
    "sasac.gov.cn": 9, "csrc.gov.cn": 9, "sse.com.cn": 8, "szse.cn": 8,
    "bse.cn": 8, "cnfin.com": 8, "xinhuanet.com": 8, "news.cn": 8,
    "people.com.cn": 8, "rmzxw.com.cn": 7, "cen.com.cn": 7,
    "cet.com.cn": 7, "cnenergynews.cn": 7, "shenhuachina.com": 9,
    "shenhuachina.com.cn": 9, "shenhua.cc": 8, "csec.com": 8,
    "china-tender.com.cn": 7, "cntcitc.com.cn": 7, "chinabidding.cn": 7,
    "stcn.com": 7, "cs.com.cn": 7, "cnstock.com": 7, "jwview.net": 7,
    "chinanews.com.cn": 7, "thepaper.cn": 6, "163.com": 4, "sina.com.cn": 5,
    "iea.org": 8, "ifc.org": 8,
}

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/122.0 Safari/537.36')
HEADERS = {'User-Agent': USER_AGENT, 'Accept-Language': 'zh-CN,zh;q=0.9'}

SO_BLOCK_RE = re.compile(r'<li\s+class="res-list[^>]*>(.*?)</li>', re.S | re.I)
SO_TITLE_RE = re.compile(r'<h3[^>]*class="res-title[^"]*"[^>]*>\s*<a\b([^>]*)>(.*?)</a>', re.S | re.I)
SO_DESC_RE = re.compile(r'<p\s+class="res-desc"[^>]*>(.*?)</p>', re.S | re.I)
SO_SUMMARY_RE = re.compile(r'<span\s+data-result-summary[^>]*>(.*?)</span>', re.S | re.I)
SO_CITE_RE = re.compile(r'<p\s+class="g-linkinfo"[^>]*>.*?<cite[^>]*>(.*?)</cite>', re.S | re.I)
MDURL_RE = re.compile(r'data-mdurl="([^"]+)"')
HREF_RE = re.compile(r'href="([^"]+)"')
BING_BLOCK_RE = re.compile(r'<li\s+class="b_algo"[^>]*>(.*?)</li>', re.S | re.I)
BING_H2_RE = re.compile(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
P_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.S | re.I)


def strip_tags(text):
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def decode_redirect(url):
    """Decode 360/Bing wrapped links when data-mdurl is absent."""
    parsed = urlparse(url)
    if 'so.com' in parsed.netloc:
        m = HREF_RE.search(url)
        return html.unescape(m.group(1)) if m else url
    if 'bing.com' in parsed.netloc and '/ck/a' in parsed.path:
        encoded = parse_qs(parsed.query).get('u', [''])[0]
        if encoded.startswith('a1'):
            raw = encoded[2:] + '=' * (-len(encoded[2:]) % 4)
            try:
                return base64.urlsafe_b64decode(raw).decode('utf-8', 'ignore')
            except Exception:
                pass
    return unquote(url)


def parse_date(text, reference_date):
    """Infer ISO date from snippet text using deterministic patterns."""
    m = re.search(r'(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
        except ValueError:
            pass
    m = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
    if m:
        try:
            return datetime(reference_date.year, int(m.group(1)), int(m.group(2))).date().isoformat()
        except ValueError:
            pass
    m = re.search(r'(\d+)\s*(天|小时)前', text)
    if m:
        return (reference_date - timedelta(days=int(m.group(1)))).date().isoformat()
    return None


def domain_of(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ''


def score_item(item, keywords, reference_date):
    domain = domain_of(item['url'])
    authority = 0
    for suffix, weight in AUTHORITY.items():
        if suffix in domain:
            authority = weight
            break
    recency = 0.0
    if item['date']:
        try:
            age = (reference_date - datetime.fromisoformat(item['date']).date()).days
            recency = max(0.0, min(12.0, 12.0 - max(0, age) / 3.0))
        except ValueError:
            pass
    blob = (item['title'] + ' ' + item['snippet'] + ' ' + item['url']).lower()
    hits = sum(1 for kw in keywords if kw.lower() in blob)
    noise_terms = ['申赎清单', '360文库', 'wenku.so.com', 'ai.so.com', 'aiassistant', 'ai助手']
    noise = sum(1 for term in noise_terms if term in blob)
    return round(max(0.0, authority + recency + 1.5 * hits - 6.0 * noise), 2)


def parse_so_page(page_html):
    items = []
    for block in SO_BLOCK_RE.findall(page_html):
        m = SO_TITLE_RE.search(block)
        if not m:
            continue
        attrs, raw_title = m.group(1), m.group(2)
        mdurl = MDURL_RE.search(attrs)
        href = HREF_RE.search(attrs)
        url = html.unescape(mdurl.group(1) if mdurl else (href.group(1) if href else ''))
        if not mdurl:
            url = decode_redirect(url)
        desc = SO_DESC_RE.search(block)
        summary = SO_SUMMARY_RE.search(desc.group(1)) if desc else None
        snippet = strip_tags(summary.group(1) if summary else (desc.group(1) if desc else ''))
        cite = SO_CITE_RE.search(block)
        items.append({
            'title': strip_tags(raw_title),
            'url': url,
            'snippet': snippet[:800],
            'cite': strip_tags(cite.group(1)) if cite else '',
        })
    return items


def parse_bing_page(page_html):
    items = []
    for block in BING_BLOCK_RE.findall(page_html):
        m = BING_H2_RE.search(block)
        if not m:
            continue
        url, raw_title = m.group(1), m.group(2)
        snippets = [strip_tags(s) for s in P_RE.findall(block)]
        items.append({
            'title': strip_tags(raw_title),
            'url': decode_redirect(html.unescape(url)),
            'snippet': ' '.join(s for s in snippets if len(s) > 10)[:800],
            'cite': '',
        })
    return items


def fetch_query(query, max_results, timeout, sleep, engine):
    engines = [engine] if engine != 'auto' else ['so360', 'bing']
    raw = []
    for eng in engines:
        url = ('https://www.so.com/s?q=' + quote(query) if eng == 'so360'
               else 'https://www.bing.com/search?q=' + quote(query) + '&count=' + str(max(10, max_results * 2)))
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            raw = parse_so_page(response.text) if eng == 'so360' else parse_bing_page(response.text)
        except Exception as exc:
            print('SEARCH_ERROR engine={} query={!r} error={}'.format(eng, query, exc), file=sys.stderr)
            raw = []
        if raw:
            break
        time.sleep(sleep)
    time.sleep(sleep)
    return raw[:max_results * 2]


def main():
    parser = argparse.ArgumentParser(description='Deterministically collect web search results.')
    parser.add_argument('--queries', nargs='+', default=[])
    parser.add_argument('--query-file', help='UTF-8 file, one query per line.')
    parser.add_argument('--out', required=True)
    parser.add_argument('--max', type=int, default=8, help='Max unique results kept per query.')
    parser.add_argument('--days', type=int, default=0, help='Only keep dated items within N days (0 disables).')
    parser.add_argument('--keywords', nargs='*', default=[], help='Scoring keywords.')
    parser.add_argument('--reference-date', default=datetime.now().date().isoformat())
    parser.add_argument('--engine', choices=['so360', 'bing', 'auto'], default='auto')
    parser.add_argument('--sleep', type=float, default=0.6)
    parser.add_argument('--timeout', type=int, default=15)
    args = parser.parse_args()

    queries = list(args.queries)
    if args.query_file:
        with open(args.query_file, encoding='utf-8') as handle:
            queries += [line.strip() for line in handle if line.strip() and not line.startswith('#')]
    if not queries:
        parser.error('Provide --queries or --query-file.')

    reference_date = datetime.fromisoformat(args.reference_date).date()
    seen, query_log = {}, []
    for query in queries:
        raw = fetch_query(query, args.max, args.timeout, args.sleep, args.engine)
        kept = 0
        for item in raw:
            if not item['title'] or not item['url'].startswith('http'):
                continue
            item['date'] = parse_date(item['snippet'] + ' ' + item['cite'] + ' ' + item['title'], reference_date)
            if args.days and item['date']:
                age = (reference_date - datetime.fromisoformat(item['date']).date()).days
                if age < 0 or age > args.days:
                    continue
            item['source'] = domain_of(item['url'])
            item['score'] = score_item(item, args.keywords, reference_date)
            item['query'] = query
            item['id'] = hashlib.sha1(item['url'].encode('utf-8')).hexdigest()[:12]
            if item['id'] not in seen or item['score'] > seen[item['id']]['score']:
                seen[item['id']] = item
                kept += 1
        query_log.append({'query': query, 'raw_results': len(raw), 'kept': kept})

    items = sorted(seen.values(), key=lambda x: (-x['score'], x['title']))
    payload = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'reference_date': reference_date.isoformat(),
        'engine_policy': args.engine,
        'queries': queries,
        'keyword_weights': args.keywords,
        'query_log': query_log,
        'item_count': len(items),
        'deduped': sum(log['raw_results'] for log in query_log) - len(items),
        'items': items,
    }
    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print('WROTE {} items={} deduped={}'.format(args.out, len(items), payload['deduped']))


if __name__ == '__main__':
    main()
