import math
import requests
import re
import unicodedata
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from modules.game_actions import GameAction
from modules.game_stages import GameStage
from states.stage import Stage


# Helper functions
def fetch_html(url: str) -> BeautifulSoup:
    """Fetch and parse HTML from a given URL."""
    retries = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retries)
    session = requests.Session()
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    try:
        response = session.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        print(f"Failed to fetch {url}: {e}")
        return BeautifulSoup("", 'html.parser')


def get_total_pages(html: BeautifulSoup) -> int:
    """Extract the total number of pages from the page navigation panel."""
    try:
        panel = html.find('div', id='bottompanel')
        last_page_link = panel.find_all('a')[-2].text
        return int(last_page_link)
    except (AttributeError, IndexError, ValueError):
        return 1


def get_posts_from_page(game_thread: str, author: str, page: int) -> list:
    """Retrieve posts for a specific author on a specific page."""
    url = f"{game_thread}?u={author}&pagina={page}"
    html = fetch_html(url)
    return html.find_all('div', attrs={'data-num': True, 'data-autor': True})


def parse_stage(post, game_end_regex, stage_end_regex, stage_start_regex) -> GameStage:
    """Parse a single post to identify the game stage."""
    headers = post.find_all('h2')
    post_id = int(post['data-num'])
    timestamp = int(post.find("span", attrs={"data-time": True})["data-time"])

    for header in headers:
        if game_end_regex.match(header.text):
            return GameStage(post_id=post_id, game_stage=Stage.End, stage_start_time=timestamp)
        elif stage_end_regex.match(header.text):
            return GameStage(post_id=post_id, game_stage=Stage.Night, stage_start_time=timestamp)
        elif stage_start_regex.match(header.text):
            return GameStage(post_id=post_id, game_stage=Stage.Day, stage_start_time=timestamp)

    return None


def get_game_phase(game_thread: str, game_master: str) -> tuple:
    """Retrieve the current game phase from the game master's posts."""
    gm_posts_html = fetch_html(f"{game_thread}?u={game_master}")
    gm_pages = get_total_pages(gm_posts_html)

    game_end_regex = re.compile('^Final de la partida')
    stage_end_regex = re.compile('^Final del día [0-9]*')
    stage_start_regex = re.compile('^Día [0-9]*')

    for page in range(gm_pages, 0, -1):
        posts = get_posts_from_page(game_thread, game_master, page)
        for post in reversed(posts):
            stage = parse_stage(post, game_end_regex, stage_end_regex, stage_start_regex)
            if stage:
                return stage

    return GameStage(post_id=1, game_stage=Stage.Night, stage_start_time=0)


def get_player_list(game_thread: str, start_day_post_id: int) -> list:
    """Retrieve the list of alive players from a specified post."""
    page_number = get_page_number_from_post(start_day_post_id)
    html = fetch_html(f'{game_thread}/{page_number}')
    posts = html.find_all('div', attrs={'data-num': True, 'data-autor': True})

    for post in posts:
        if int(post['data-num']) == start_day_post_id:
            players = post.find('ol').find_all('a')
            return [player.text.lower().strip() for player in players]

    return []


def get_last_event(game_thread: str, bot_id: str, event_regex: str) -> int:
    """Get the last occurrence of a specified event based on regex from bot posts."""
    bot_posts_html = fetch_html(f"{game_thread}?u={bot_id}")
    bot_pages = get_total_pages(bot_posts_html)

    for page in range(bot_pages, 0, -1):
        posts = get_posts_from_page(game_thread, bot_id, page)
        for post in reversed(posts):
            headers = post.find_all('h2')
            for header in headers:
                if re.match(event_regex, header.text):
                    return int(post['data-num'])

    return 1


def get_last_votecount(game_thread: str, bot_id: str) -> tuple:
    """Get the post ID of the last votecount pushed and if it was an EoD votecount."""
    votecount_id = get_last_event(game_thread, bot_id, '^Recuento de votos$')
    lynch_id = get_last_event(game_thread, bot_id, '^Recuento de votos final$')
    return (votecount_id, lynch_id == votecount_id)


def get_last_post(game_thread: str) -> int:
    """Get the post ID of the last posted message."""
    last_page = request_page_count(game_thread)
    html = fetch_html(f'{game_thread}/{last_page}')
    posts = html.find_all('div', attrs={'data-num': True, 'data-autor': True})
    return int(posts[-1]['data-num']) if posts else 1


def get_actions_from_page(game_thread: str, page_to_scan: int, start_from_post: int) -> list:
    """Retrieve all game actions from a specific page starting from a given post."""
    html = fetch_html(f'{game_thread}/{page_to_scan}')
    posts = html.find_all('div', class_=['cf post', 'cf post z', 'cf post first'])
    actions = []

    for post in posts:
        post_id = int(post['data-num'])
        if post_id > start_from_post:
            commands = post.find('div', class_='post-contents').find_all('h4')
            for command in commands:
                action = GameAction(
                    post_id=post_id,
                    post_time=int(post.find('span', class_='rd')['data-time']),
                    contents=unicodedata.normalize("NFKC", command.text.lower()),
                    author=post['data-autor'].lower()
                )
                actions.append(action)

    return actions


def request_page_count(game_thread: str) -> int:
    """Retrieve the total number of pages in the game thread."""
    html = fetch_html(game_thread)
    return get_total_pages(html)


def get_page_number_from_post(post_id: int) -> int:
    """Calculate the page number of a given post based on 30 posts per page."""
    return math.ceil(post_id / 30)
