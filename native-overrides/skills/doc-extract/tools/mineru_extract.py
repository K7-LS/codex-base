#!/usr/bin/env python
"""MinerU extract helper — дефолт pipeline+ru, авто-сплит больших PDF на батчи, склейка MD.

Использование:
  python mineru_extract.py <input.pdf> [-o out.md] [--pages 1-20] [--chunk 180] [--model pipeline] [--lang ru]

Токен MinerU берётся только из env MINERU_API_TOKEN.
Нельзя vlm на русском (калечит кириллицу) — дефолт pipeline. Одиночный лимит облака ~200-600 стр →
большие тома режутся на чанки по --chunk страниц и склеиваются.
"""
import os, sys, json, time, argparse, zipfile, io
import requests

API = 'https://mineru.net/api/v4'

def get_token():
    return os.environ.get('MINERU_API_TOKEN')

def parse_chunk(pdf_bytes, name, token, model, lang):
    H = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    r = requests.post(API + '/file-urls/batch', headers=H, json={
        'enable_formula': True, 'enable_table': True,
        'model_version': model, 'language': lang,
        'files': [{'name': name}]}, timeout=60).json()
    if r.get('code') != 0:
        raise RuntimeError('submit: ' + json.dumps(r, ensure_ascii=False)[:200])
    bid = r['data']['batch_id']; up = r['data']['file_urls'][0]
    pr = requests.put(up, data=pdf_bytes, timeout=300)   # requests не добавляет Content-Type -> совпадает с OSS-подписью
    if pr.status_code != 200:
        raise RuntimeError('upload HTTP ' + str(pr.status_code))
    url = API + '/extract-results/batch/' + bid
    for _ in range(90):
        d = requests.get(url, headers={'Authorization': 'Bearer ' + token}, timeout=60).json()
        files = d.get('data', {}).get('extract_result', []) or []
        states = [f.get('state') for f in files]
        if files and all(s == 'done' for s in states):
            zb = requests.get(files[0]['full_zip_url'], timeout=180).content
            return zipfile.ZipFile(io.BytesIO(zb)).read('full.md').decode('utf-8', 'replace')
        if any(s in ('failed', 'error') for s in states):
            raise RuntimeError('parse: ' + json.dumps(files, ensure_ascii=False)[:200])
        time.sleep(10)
    raise RuntimeError('timeout batch ' + bid)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('-o', '--out')
    ap.add_argument('--pages', help='напр. 1-20 (1-based); весь документ если опущено')
    ap.add_argument('--chunk', type=int, default=180, help='макс. страниц в облачный батч (запас под лимит)')
    ap.add_argument('--model', default='pipeline')
    ap.add_argument('--lang', default='ru')
    a = ap.parse_args()
    token = get_token()
    if not token:
        sys.exit('Нет токена MinerU: требуется env MINERU_API_TOKEN')
    if a.model == 'vlm' and a.lang == 'ru':
        print('WARN: vlm на русском калечит кириллицу — рекомендуется pipeline', file=sys.stderr)
    import fitz
    doc = fitz.open(a.pdf)
    n = doc.page_count
    if a.pages:
        s, _, e = a.pages.partition('-')
        s = int(s) - 1; e = int(e) if e else s + 1
        pageset = list(range(max(0, s), min(e, n)))
    else:
        pageset = list(range(n))
    out = a.out or os.path.splitext(a.pdf)[0] + '.mineru.md'
    parts = []
    part_files = []
    nchunks = (len(pageset) + a.chunk - 1) // a.chunk
    for ci in range(nchunks):
        chunk = pageset[ci * a.chunk:(ci + 1) * a.chunk]
        # partial-save/resume: готовый чанк сохраняется сразу — падение сети на
        # N-м чанке не сжигает облачную квоту предыдущих; перезапуск той же
        # командой продолжает с места падения
        part_path = '%s.part%02d.md' % (out, ci)
        part_files.append(part_path)
        if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
            md = open(part_path, encoding='utf-8').read()
            print('[chunk %d/%d] уже готов — resume из %s' % (
                ci + 1, nchunks, os.path.basename(part_path)), flush=True)
        else:
            nd = fitz.open()
            for p in chunk:
                nd.insert_pdf(doc, from_page=p, to_page=p)
            buf = nd.tobytes(); nd.close()
            print('[chunk %d/%d] стр %d-%d (%dp) -> MinerU %s/%s...' % (
                ci + 1, nchunks, chunk[0] + 1, chunk[-1] + 1, len(chunk), a.model, a.lang), flush=True)
            for attempt in (1, 2, 3):
                try:
                    md = parse_chunk(buf, 'chunk_%d.pdf' % ci, token, a.model, a.lang)
                    break
                except Exception as e:
                    if attempt == 3:
                        print('FAIL chunk %d после 3 попыток. Готовые чанки лежат в *.partNN.md — '
                              'перезапусти той же командой, продолжу с этого места.' % (ci + 1),
                              file=sys.stderr)
                        raise
                    wait = 30 * attempt
                    print('[chunk %d/%d] попытка %d: %s — повтор через %d с' % (
                        ci + 1, nchunks, attempt, e, wait), file=sys.stderr, flush=True)
                    time.sleep(wait)
            open(part_path, 'w', encoding='utf-8').write(md)
        parts.append('\n\n<!-- стр %d-%d -->\n\n%s' % (chunk[0] + 1, chunk[-1] + 1, md))
    open(out, 'w', encoding='utf-8').write(''.join(parts))
    for pf in part_files:  # сборка успешна — промежуточные части не нужны
        try:
            os.remove(pf)
        except OSError:
            pass
    print('SAVED:', out, '| chars:', sum(len(p) for p in parts), '| chunks:', nchunks)

if __name__ == '__main__':
    main()
