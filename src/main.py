import logging
import re
import requests_cache

from typing import Pattern
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from tqdm import tqdm
from collections import defaultdict

from configs import configure_argument_parser, configure_logging
from constants import (
    BASE_DIR,
    MAIN_DOC_URL,
    PEP,
    EXPECTED_STATUS,
)
from outputs import control_output
from utils import get_response, find_tag


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')

    section_tag = find_tag(
        soup,
        "section",
        attrs={"id": "what-s-new-in-python"}
    )
    div_tag = find_tag(
        section_tag, "div",
        attrs={"class": "toctree-wrapper compound"}
    )
    li_tag = div_tag.find_all("li", class_="toctree-l1")
    results = [
        ('Ссылка на статью', 'Заголовок', 'Редактор, Автор')
    ]
    for i in tqdm(li_tag):
        a_tag = find_tag(i, "a")["href"]
        string = urljoin(whats_new_url, a_tag)

        response = get_response(session, string)
        if response is None:
            return
        soup = BeautifulSoup(response.text, "lxml")
        h1 = find_tag(soup, "h1")
        dl = find_tag(soup, "dl")
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (string, h1.text, dl_text)
        )
    return results


def latest_versions(session):
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, "lxml")

    sidebar = find_tag(soup, "div", attrs={"class": "sphinxsidebarwrapper"})
    ul_tags = sidebar.find_all("ul")
    for ul in tqdm(ul_tags, desc="Поиск тэгов 'a'"):
        if "All versions" in ul.text:
            all_a_tags = ul.find_all("a")
            break
    else:
        raise Exception("Ничего не нашлось!")

    pattern = r"Python\s([\d\.]+)\s\((\w{1,}.*)\)"
    results = [
        ('Ссылка на документацию', 'Версия', 'Статус')
    ]
    for i in tqdm(all_a_tags, desc="Разбор содержимого тэга 'a'"):
        result = re.search(pattern, i.text)
        if result:
            version, status = result.groups()
        else:
            version, status = i.text, ''
        results.append(
            (i["href"], version, status)
        )
    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)
    if response is None:
        return

    soup = BeautifulSoup(response.text, 'lxml')
    main_role = find_tag(soup, "div", attrs={"role": "main"})
    table = find_tag(main_role, "table", attrs={"class": "docutils"})
    pattern: Pattern[str] = re.compile(r'.*pdf-a4\.zip$')
    a_tag = find_tag(table, "a", attrs={"href": pattern})
    pdf_link = a_tag["href"]

    download_link = urljoin(downloads_url, pdf_link)
    obj_name = download_link.split("/")[-1]

    downloads_dir = BASE_DIR / "downloads"
    downloads_dir.mkdir(exist_ok=True)

    archive_path = downloads_dir / obj_name
    download = session.get(download_link)
    with open(archive_path, mode='wb') as file:
        file.write(download.content)
    logging.info(f"Архив был загружен и сохранён: {archive_path}")


def pep(session):
    response = get_response(session, PEP)
    result = [('Статус', 'Количество')]
    soup = BeautifulSoup(response.text, features='lxml')
    all_tables = soup.find('section', id='numerical-index')
    all_tables = all_tables.find_all('tr')
    pep_count = 0
    status_count = defaultdict(int)
    for table in tqdm(all_tables, desc='Parsing'):
        rows = table.find_all('td')
        all_status = None
        link = None
        for i, row in enumerate(rows):
            if i == 0 and len(row.text) == 2:
                all_status = row.text[1]
                continue
            if i == 1:
                link_tag = find_tag(row, 'a')
                link = link_tag['href']
                break
        link = urljoin(PEP, link)
        response = get_response(session, link)
        soup = BeautifulSoup(response.text, features='lxml')
        dl = find_tag(soup, 'dl', attrs={'class': 'rfc2822 field-list simple'})
        pattern = (
                r'.*(?P<status>Active|Draft|Final|Provisional|Rejected|'
                r'Superseded|Withdrawn|Deferred|April Fool!|Accepted)'
            )
        re_text = re.search(pattern, dl.text)
        status = None
        if re_text:
            status = re_text.group('status')
        if all_status and EXPECTED_STATUS.get(all_status) != status:
            logging.info(
                f'Несовпадающие статусы:\n{link}\n'
                f'Статус в карточке: {status}\n'
                f'Ожидаемый статус: {EXPECTED_STATUS[all_status]}'
            )
        if not all_status and status not in ('Active', 'Draft'):
            logging.info(
                f'Несовпадающие статусы:\n{link}\n'
                f'Статус в карточке: {status}\n'
                f'Ожидаемые статусы: ["Active", "Draft"]'
            )
        pep_count += 1
        status_count[status] += 1
    result.extend([(status, status_count[status]) for status in status_count])
    result.append(('Total', pep_count))
    return result


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')

    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()

    logging.info(f'Аргументы командной строки: {args}')

    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
