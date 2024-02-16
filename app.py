from collections import namedtuple
import os
import re

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import requests
import yaml

from mwconstants import WIKIPEDIA_LANGUAGES

app = Flask(__name__)

__dir__ = os.path.dirname(__file__)
app.config.update(
    yaml.safe_load(open(os.path.join(__dir__, 'default_config.yaml'))))
try:
    app.config.update(
        yaml.safe_load(open(os.path.join(__dir__, 'config.yaml'))))
except IOError:
    # It is ok if there is no local config file
    pass

# Enable CORS for API endpoints
#CORS(app, resources={'*': {'origins': '*'}})
CORS(app)

ResultRecord = namedtuple('ResultRecord', ['page_title', 'qid', 'source', 'redlink'])

@app.route('/')
def index():
    return render_template('index.html',
                           page_title=set_title(), lang=set_lang(), k=set_k('results'))


@app.route('/compare')
def compare():
    return render_template('compare.html',
                           qid=set_qid(), lang=set_lang(), k=set_k())


@app.route('/api/serpentine')
def query_apis():
    # TODO error handling
    lang = set_lang()
    title = set_title()
    qid = set_qid()
    if qid is None:
        qid = title_to_qid(lang=lang, title=title)

    # TODO: actually incorporate offsets on backend for reader/link requests instead of hacking and update this code
    # NOTE: I double the k inputs to the models to better guarantee returning enough results after deduplicating
    overall_k = 0
    try:
        links_k = set_k('links')
        overall_k += links_k
        results_links = fetch_links_results(lang=lang, qid=qid, title=title, k=links_k*2, offset=set_offset('links'))
    except Exception:
        results_links = []

    try:
        reader_k = set_k('reader')
        overall_k += reader_k
        results_reader = fetch_reader_results(lang=lang, qid=qid, k=reader_k*2, offset=set_offset('reader'))
    except Exception:
        results_reader = []

    results_morelike = []
    try:
        morelike_k = set_k('morelike')
        overall_k += morelike_k
        results_morelike = fetch_morelike_results(lang=lang, title=title, k=morelike_k*2, offset=set_offset('morelike'))
    except Exception:
        pass

    results_serpentined = []
    pages_added = {qid, title}
    # TODO: more random serpentining of sources?
    # TODO: deduplicate code
    max_num_results = max([len(results_links), len(results_morelike), len(results_reader)])
    for i in range(0, max_num_results):
        if i < len(results_links):
            page = results_links[i].qid if results_links[i].qid else results_links[i].page_title
            if page not in pages_added:
                results_serpentined.append(results_links[i]._asdict())
                pages_added.add(page)
        if i < len(results_morelike):
            page = results_morelike[i].qid if results_morelike[i].qid else results_morelike[i].page_title
            if page not in pages_added:
                results_serpentined.append(results_morelike[i]._asdict())
                pages_added.add(page)
        if i < len(results_reader):
            page = results_reader[i].qid if results_reader[i].qid else results_reader[i].page_title
            if page not in pages_added:
                results_serpentined.append(results_reader[i]._asdict())
                pages_added.add(page)
        if len(results_serpentined) >= overall_k:
            break

    # all results need a wikidata description to help users evaluate whether article is a match
    add_wikidata_descriptions(lang, results_serpentined)
    # some API backends provide QIDs and not titles so here we fill in the blanks
    add_article_titles(lang, results_serpentined)
    # for QIDs lacking in a local article, we use a Wikidata label as back-up title
    add_wikidata_labels(lang, results_serpentined)

    return jsonify({'results': results_serpentined, 'qid': qid})

def add_wikidata_descriptions(lang, pages):
    """Add Wikidata descriptions to results for easier scanning."""
    # Example query:
    # https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q2084556|Q15985294&props=descriptions&languages=en&format=json
    qids_to_page_idx = {page['qid']:i for i, page in enumerate(pages) if page['qid']}
    max_per_query = 50
    for idx in range(0, len(qids_to_page_idx), max_per_query):
        qid_set = [qid for qid in qids_to_page_idx if qids_to_page_idx[qid] >= idx and qids_to_page_idx[qid] < idx+max_per_query]
        wikibase_url = "https://www.wikidata.org/w/api.php"
        params = {'action': 'wbgetentities',
                  'ids': '|'.join(qid_set),
                  'props': 'descriptions',
                  'languages': lang,
                  'format': 'json'}
        response = requests.get(wikibase_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
        results = response.json()
        for item in results.get('entities', {}).values():
            qid = item.get('id')
            wikidata_description = item.get('descriptions', {}).get(lang, {}).get('value')
            if wikidata_description and qid in qids_to_page_idx:
                pages[qids_to_page_idx[qid]]['description'] = wikidata_description


def add_article_titles(lang, pages):
    wiki = f'{lang}wiki'
    qids_to_page_idx = {page['qid']: i for i, page in enumerate(pages) if page['qid'] and page['page_title'] == "-"}
    max_per_query = 50
    for idx in range(0, len(qids_to_page_idx), max_per_query):
        qid_set = [qid for qid in qids_to_page_idx if
                   qids_to_page_idx[qid] >= idx and qids_to_page_idx[qid] < idx + max_per_query]
        wikibase_url = "https://www.wikidata.org/w/api.php"
        params = {
            'action': 'wbgetentities',
            'props': 'sitelinks',
            'format': 'json',
            'formatversion': 2,
            'sitefilter': wiki,
            'ids': '|'.join(qid_set)
        }
        response = requests.get(wikibase_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
        results = response.json()
        for item in results.get('entities', {}).values():
            qid = item.get('id')
            page_title = item.get('sitelinks', {}).get(wiki, {}).get('title')
            if page_title and qid in qids_to_page_idx:
                pages[qids_to_page_idx[qid]]['page_title'] = page_title
                pages[qids_to_page_idx[qid]]['redlink'] = False


def add_wikidata_labels(lang, pages):
    qids_to_page_idx = {page['qid']: i for i, page in enumerate(pages) if page['qid'] and page['page_title'] == "-"}
    max_per_query = 50
    wikibase_url = "https://www.wikidata.org/w/api.php"
    for idx in range(0, len(qids_to_page_idx), max_per_query):
        qid_set = [qid for qid in qids_to_page_idx if
                   qids_to_page_idx[qid] >= idx and qids_to_page_idx[qid] < idx + max_per_query]
        params = {
            'action': 'wbgetentities',
            'props': 'labels',
            'ids': '|'.join(qid_set),
            'format': 'json',
            'formatversion': 2
        }
        response = requests.get(wikibase_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
        results = response.json()
        for item in results.get('entities', {}).values():
            try:
                qid = item.get('id')
                labels = item.get('labels', {})
                if lang in labels:
                    pages[qids_to_page_idx[qid]]['page_title'] = labels[lang]['value']
                elif 'en' in labels:
                    pages[qids_to_page_idx[qid]]['page_title'] = labels['en']['value']
                elif labels:  # still try to return something if not in requested language or English
                    first_lang = list(labels.keys())[0]
                    pages[qids_to_page_idx[qid]]['page_title'] = labels[first_lang]['value']
            except (KeyError, IndexError):
                continue


def fetch_morelike_results(lang, title, k, offset=0):
    morelike_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {'action': 'query',
              'prop': 'pageprops',
              'ppprop': 'wikibase_item',
              'generator': 'search',
              'gsrlimit': k,
              'gsroffset': offset,
              'gsrsearch': f'morelike:{title}',
              'gsrprop': '',
              'format': 'json'}
    response = requests.get(morelike_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
    results = response.json()
    pages = []
    redlink = False  # local language API so article by definition exists
    for page in results.get('query', {}).get('pages', {}).values():
        page_title = page.get('title')
        page_qid = page.get('pageprops', {}).get('wikibase_item')
        pages.append(ResultRecord(page_title, page_qid, 'morelike', redlink))
    return pages

def fetch_reader_results(lang, qid, k, offset=0):
    reader_url = "https://reader.wmcloud.org/api/v1/list-reader"
    params = {'lang': lang,
              'qid': qid,
              'k': offset+k}
    response = requests.get(reader_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
    results = response.json()
    pages = []
    for page in results[offset:]:
        page_title = page.get('title', '-').replace('_', ' ')
        page_qid = page.get('qid')
        redlink = (page_title == '-')
        pages.append(ResultRecord(page_title, page_qid, 'reader', redlink))
    return pages

def fetch_links_results(lang, qid, title, k, offset=0):
    links_url = "https://vector-search.wmcloud.org/collections/list-building-tool/points/search"
    pages = []
    # first we get the embedding for a QID
    embedding_lookup_params = {
        "with_payload": True,
        "with_vector": True,
        "filter": {"must": [{"key": "name", "match": {"value": qid}}]},
        # This is a required field so we're sending a dummy vector.
        # The actual pruning happens using payload filters.
        "vector": [0] * 50,
        "limit": 1,
    }
    response = requests.post(links_url, json=embedding_lookup_params,
                             headers={'User-Agent': app.config['CUSTOM_UA']})
    embeddings = response.json().get("result")
    if not embeddings:
        emb_url = "https://content-similarity-outlinks.wmcloud.org/api/v1/embedding"
        params = {'lang': lang,
                  'qid': qid,
                  'title': title}
        response = requests.get(emb_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
        embeddings = response.json()
        if not embeddings[0]["vector"]:
            embeddings = None

    if embeddings:
        embedding = embeddings[0]["vector"]
        nearest_neighbors_params = {
            "with_payload": True,
            "with_vector": False,
            "vector": embedding,
            "limit": k,
            "offset": offset,
        }
        response = requests.post(links_url, json=nearest_neighbors_params,
                                 headers={'User-Agent': app.config['CUSTOM_UA']})
        neighbors = response.json().get("result")
        if neighbors:
            page_title = "-"  # API doesn't provide page title so we use placeholder that will later be overwritten
            redlink = True  # this will be set to False if a page is found in the local language
            for page in neighbors:
                page_qid = page.get("payload", {}).get("name")
                if page_qid:
                    pages.append(ResultRecord(page_title, page_qid, 'links', redlink))

    return pages


def set_qid():
    if 'qid' in request.args:
        qid = request.args['qid'].upper()
        if re.match('^Q[0-9]+$', qid):
            return qid
    return None

def set_lang():
    if 'lang' in request.args:
        lang = request.args['lang'].lower()
        if lang in WIKIPEDIA_LANGUAGES:
            return lang
        elif lang == 'wikidata':
            return lang
    return None

def set_k(source='reader'):
    k = 10
    if f'k-{source}' in request.args:
        try:
            arg_k = int(request.args[f'k-{source}'])
            if arg_k >= 1:
                k = arg_k
        except ValueError:
            pass
    return k

def set_offset(source='reader'):
    offset = 0
    if f'offset-{source}' in request.args:
        try:
            arg_offset = int(request.args[f'offset-{source}'])
            if arg_offset >= 1:
                offset = arg_offset
        except ValueError:
            pass
    return offset

def set_title():
    if 'page_title' in request.args:
        title = request.args['page_title']
    elif 'title' in request.args:
        title = request.args['title']
    else:
        title = None

    if title:
        title = title.replace('_', ' ').strip()
        try:
            title = title[0].capitalize() + title[1:]
        except IndexError:
            title = None
    return title

def title_to_qid(lang, title):
    """Get Wikidata item ID for a given Wikipedia article"""

    pageprops_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {'action': 'query',
              'prop': 'pageprops',
              'ppprop': 'wikibase_item',
              'redirects': True,
              'titles': title,
              'format': 'json',
              'formatversion': 2}
    response = requests.get(pageprops_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
    result = response.json()

    try:
        return result['query']['pages'][0]['pageprops']['wikibase_item']
    except (KeyError, IndexError):
        return None

def qid_to_title(qid, lang):
    """Get Wikidata item ID for a given Wikipedia article"""

    labels_url = "https://wikidata.org/w/api.php"
    params = {'action': 'wbgetentities',
              'ids': qid,
              'props': 'labels',
              'format': 'json',
              'formatversion': 2}
    response = requests.get(labels_url, params=params, headers={'User-Agent': app.config['CUSTOM_UA']})
    result = response.json()

    try:
        labels = result['entities'][qid]['labels']
        if lang in labels:
            return labels[lang]['value']
        elif 'en' in labels:
            return labels['en']['value']
        else:  # still try to return something if not in requested language or English
            first_lang = list(labels.keys())[0]
            return labels[first_lang]['value']
    except (KeyError, IndexError):
        pass
    return '-'
