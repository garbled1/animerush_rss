"""
Scrape the list of ongoing anime, maybe subscribe to them.
"""

import os
import re
import requests
import argparse
import yaml
import feedparser
from rich import print
from rich.console import Console
from pprint import pprint
from bs4 import BeautifulSoup
from PyInquirer import prompt
from prompt_toolkit.validation import Validator, ValidationError
from anime_downloader.sites.animerush import AnimeRush, AnimeRushEpisode
from anime_downloader.util import setup_logger, external_download
from anime_downloader.sites import exceptions as a_exceptions
from urllib import error as u_errors


class NumberValidator(Validator):
    def validate(self, document):
        try:
            int(document.text)
        except ValueError:
            raise ValidationError(
                message='Please enter a number',
                cursor_position=len(document.text))  # Move cursor to end


class AnimeRushRSS:
    url = 'http://www.animerush.tv/rss.xml'
    rss = None

    def __init__(self):
        return

    def load_rss(self):
        self.rss = feedparser.parse(self.url)
        if 'title' in self.rss.feed and 'AnimeRush' in self.rss.feed.title:
            return True
        return False

    def show_name(self, episode):
        """Return the show name only"""
        # return re.sub(re.compile(' *episode *[0-9]*'), '', title)
        return episode.tags[0]['term']

    def ep_num(self, episode):
        """Return the episode number only"""
        return re.sub(re.compile('.* episode *'), '', episode.title)

    def get_entries(self):
        """Just return the entries list"""
        return self.rss.entries



class AnimeRushOngoing:
    url = 'https://www.animerush.tv/'
    ongoing_list = []

    def __init__(self):
        return

    def get_page(self):
        headers = {
            "Accept": "*/*",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36",
        }
        x = requests.get(self.url, headers=headers)
        soup = BeautifulSoup(x.text, 'html.parser')

        return soup

    def build_list(self, soup):
        season_bits = [
            '0th', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th',
        ]
        for anime in soup.find_all('div', attrs={'class': 'airing_box_mid_link'}):
            anime_descendants = anime.descendants
            for d in anime_descendants:
                if d.name == 'a' and d.get('class', '') == ['full_click']:
                    a_dict = dict()
                    season = 1
                    fix_str = d.text.encode("ascii", 'ignore')
                    name = fix_str.decode()
                    name = name.replace('/', '+')
                    for (i, sea) in enumerate(season_bits):
                        if ' Season' in name:
                            season = i
                            name = re.sub(re.compile(' *' + sea + ' Season'), '', name)
                    for i in range(1, 9):
                        ss = 'Season ' + str(i)
                        if 'ss' in name:
                            season = i
                            name = re.sub(re.compile(' *' + ss), '', name)
                        if name.endswith(' S' + str(i)):
                            season = i
                            name = re.sub(re.compile(' \(*S' + str(i) + '\)*$'), '', name)
                        if name.endswith(' ' + str(i)):
                            season = i
                            name = re.sub(re.compile(' ' + str(i) + '$'), '', name)
                    if 'OVA' in name:
                        season = 0
                        name = re.sub(re.compile(' OVA'), '', name)
                    if 'Special' in name:
                        season = 0
                        name = re.sub(re.compile(' Specials*'), '', name)
                    a_dict['full_name'] = d.text
                    if not d['href'].startswith('http'):
                        a_dict['url'] = 'https:' + d['href']
                    else:
                        a_dict['url'] = d['href']
                    a_dict['name'] = name
                    a_dict['season'] = season
                    self.ongoing_list.append(a_dict)

        return self.ongoing_list


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--directory', action='store',
                        dest='directory', default='./',
                        help='Base directory to store files')
    parser.add_argument('-c', '--conf', action='store',
                        dest='conffile', default='./ar_conf.yml',
                        help='Configuration file')
    parser.add_argument('-p', '--pick_anime', action='store_true',
                        dest='pick_anime', default=False,
                        help='Pick Anime to monitor')
    parser.add_argument('-i', '--initial_download_all', action='store_true',
                        dest='initial_download_all', default=False,
                        help='Perform an initial download of all monitored anime')
    parser.add_argument('-s', '--single_initial_download', action='store_true',
                        dest='single_initial_download', default=False,
                        help='Perform an initial download of one monitored anime')
    parser.add_argument('-a', '--ask-initial',
                        action='store_true',
                        dest='ask_initial',
                        default=False,
                        help='Confirm before downloading each anime during initial_download')
    parser.add_argument('-n', '--new_anime_check', action='store_true',
                        dest='new_anime_check', default=False,
                        help='Check for new anime')
    args = parser.parse_args()
    return args


def parse_config(conf_f):
    """Parse the config file"""
    if not os.path.exists(conf_f):
        return None
    with open(conf_f, 'r') as stream:
        try:
            parsed_yaml=yaml.safe_load(stream)
            return parsed_yaml
        except yaml.YAMLError as exc:
            print(exc)
    return None


def fix_config(current_anime, conf_f):
    """Apply any fixes to the config file"""

    changed = False
    # add season offset
    for anime in current_anime['monitored']:
        if 'season_offset' in anime:
            continue
        if not anime['monitored']:
            continue
        anime['season_offset'] = 0
        changed = True

    # all fixes applied, save config
    if changed:
        with open(conf_f, 'w') as file:
            yaml.dump(current_anime, file)
        print('[green]Applied fixes to config file ' + conf_f)

    # return config in case we changed it
    return current_anime


def find_anime_in_monitored_list(anime_name, mlist):
    """Return the dict of the monitored anime if any."""
    for a in mlist:
        if a['full_name'] == anime_name:
            return a
    return None


def new_anime_check(current_anime):
    # fetch the current list
    aro = AnimeRushOngoing()
    soup = aro.get_page()
    ogl = aro.build_list(soup)

    for anime in ogl:
        record = find_anime_in_monitored_list(anime['full_name'],
                                              current_anime['monitored'])
        if record is None:
            return True
    return False


def pick_anime(current_anime, directory):
    """Lets pick some anime to monitor."""

    # no config file, make a default
    if current_anime is None:
        current_anime = dict()
        current_anime['monitored'] = []
        current_anime['base_directory'] = directory
        current_anime['quality'] = '1080p'
        current_anime['fallback_qualities'] = [
            '1080p',
            '720p',
            '480p',
            '360p',
        ]
        current_anime['external_downloader'] = '{aria2}'

    # fetch the current list
    aro = AnimeRushOngoing()
    soup = aro.get_page()
    ogl = aro.build_list(soup)

    console = Console()
    console.clear()

    for anime in ogl:
        record = find_anime_in_monitored_list(anime['full_name'],
                                              current_anime['monitored'])
        if record is not None:
            continue
        
        console.clear()
        print('[green]Anime Name: [/green][yellow]' + anime['full_name'])
        print('[green]Directory:  [/green][yellow]' + anime['name'])
        print('[green]Season:     [/green][yellow]' + str(anime['season']))
        q_monitor = [
            {
                'type': 'confirm',
                'name': 'doit',
                'message': 'Monitor this anime?',
                'default': False,
            }
        ]
        a_monitor = prompt(q_monitor)
        if not a_monitor['doit']:
            new_entry = dict()
            new_entry['full_name'] = anime['full_name']
            new_entry['monitored'] = False
            current_anime['monitored'].append(new_entry)
            continue

        new_entry = dict()
        new_entry['full_name'] = anime['full_name']
        new_entry['monitored'] = True
        print()

        q_details = [
            {
                'type': 'input',
                'name': 'dirname',
                'message': 'Directory Name to store in: ',
                'default': anime['name'],
            },
            {
                'type': 'input',
                'name': 'season',
                'message': 'Season number',
                'validate': NumberValidator,
                'filter': lambda val: int(val),
            },
            {
                'type': 'input',
                'name': 'season_offset',
                'message': 'Season episode offset (normally 0)',
                'validate': NumberValidator,
                'filter': lambda val: int(val),
                'default': '0',
            },
        ]
        a_details = prompt(q_details)
        new_entry['name'] = a_details['dirname']
        new_entry['season'] = a_details['season']
        new_entry['season_offset'] = a_details['season_offset']
        new_entry['url'] = anime['url']
        current_anime['monitored'].append(new_entry)

    return current_anime


def gen_epname(anime, ep_num):
    """Generate a filename for a given anime"""
    filename = anime['name'] + ' - ' + 'S' + str(anime['season']).zfill(2) + 'E' + str(ep_num).zfill(2)
    return filename


def gen_epname_no_epfill(anime, ep_num):
    """Generate a filename for a given anime"""
    filename = anime['name'] + ' - ' + 'S' + str(anime['season']).zfill(2) + 'E' + str(ep_num)
    return filename


def gen_seasondir(anime):
    """Generate season directory for a given anime"""
    sdir = 'Season ' + str(anime['season']).zfill(2)
    return sdir


def gen_basedir(anime):
    """Generate a base directory for a given anime"""
    basedir = anime['name']
    return basedir


def gen_fullname(anime, basedir, ep_num):
    """Generate full pathname of anime"""
    filename = basedir + '/' + gen_basedir(anime) + '/' + gen_seasondir(anime) + '/' + gen_epname(anime, ep_num) + '.mp4'
    return filename


def have_episode(anime, ep_num, basedir):
    """Check if episode exists"""
    # make a list of potential file paths
    filepaths = []
    afn_e = anime['full_name'].encode("ascii", 'ignore')
    afn = afn_e.decode()
    afn = afn.replace(' ', '_')
    afn = afn.replace('(', '')
    afn = afn.replace(')', '')
    afn = afn.replace(':', '')
    afn = afn.replace(',', '')
    
    filepaths.append(basedir + '/' + gen_seasondir(anime) + '/' + gen_epname(anime, ep_num) + '.mp4')
    filepaths.append(basedir + '/' + gen_seasondir(anime) + '/' + gen_epname_no_epfill(anime, ep_num) + '.mp4')

    filepaths.append(basedir + '/' + gen_seasondir(anime) + '/' + afn + ' - ' + 'S' + str(anime['season']).zfill(2) + 'E' + str(ep_num) + '.mp4')
    filepaths.append(basedir + '/' + gen_seasondir(anime) + '/' + afn + ' - ' + 'S' + str(anime['season']).zfill(2) + 'E' + str(ep_num).zfill(2) + '.mp4')

    filepaths.append(basedir + '/' + gen_seasondir(anime) + '/' + afn + '_' + str(ep_num).zfill(2) + '.mp4')
    filepaths.append(basedir + '/' + gen_seasondir(anime) + '/' + afn + '_' + str(ep_num) + '.mp4')
    filepaths.append(basedir + '/' + afn + '_' + str(ep_num) + '.mp4')
    filepaths.append(basedir + '/' + afn + '_' + str(ep_num).zfill(2) + '.mp4')

    # pprint(filepaths)
    # check them all
    for path in filepaths:
        if os.path.exists(path):
            return True

    return False


def create_tree(config, anime):
    """Create the required tree to download an anime"""
    root = config['base_directory']
    basedir = gen_basedir(anime)
    sdir = gen_seasondir(anime)

    if not os.path.exists(root):
        os.mkdir(root)

    if not os.path.exists(root + '/' + basedir):
        os.mkdir(root + '/' + basedir)

    if not os.path.exists(root + '/' + basedir + '/' + sdir):
        os.mkdir(root + '/' + basedir + '/' + sdir)


def is_monitored(config, show):
    """ Do we monitor this anime?"""
    anime = find_anime_in_monitored_list(show,
                                        config['monitored'])
    if anime is None:
        return False
    return anime['monitored']


def parse_rss(config):
    """Parse the rss feed, download files"""
    rss = AnimeRushRSS()
    rss.load_rss()
    entries = rss.get_entries()
    grabbed = 0
    # setup_logger('DEBUG')
    for e in entries:
        show = rss.show_name(e)
        ep_num = rss.ep_num(e)
        orig_num = rss.ep_num(e)
        monitored = is_monitored(config, show)
        if not monitored:
            continue
        anime = find_anime_in_monitored_list(show, config['monitored'])

        # don't break specials
        if ep_num.isdigit():
            ep_num = int(ep_num) + anime['season_offset']
        else:
            part = ep_num.split('.')
            ep_num = str(int(part[0]) + anime['season_offset']) + '.' + part[1]
            
        basedir = config['base_directory'] + '/' + gen_basedir(anime)
        create_tree(config, anime)
        if not have_episode(anime, ep_num, basedir):
            print("Episode {} of {} missing, downloading".format(str(ep_num), show))
            try:
                adl = AnimeRush(anime['url'], quality=config['quality'],
                                fallback_qualities=config['fallback_qualities'])
                adl_e = AnimeRushEpisode(e.link, parent=adl, ep_no=orig_num)
            except IndexError:
                continue
            try:
                adl_e.download(path=gen_fullname(anime, config['base_directory'],
                                                 ep_num))
                grabbed = grabbed + 1
            except a_exceptions.NotFoundError:
                print("[bold red]Episode Missing!")
            except u_errors.HTTPError as e:
                if e.code > 400:
                    print("[bold red]Download error! {}".format(str(e.code)))

            # util.external_download(external_downloader, episode,
            #                        file_format, speed_limit, path=download_dir)

    return grabbed


def catch_up_all_anime(config, ask):
    """Catch up missing anime"""
    q_download = [
        {
            'type': 'confirm',
            'name': 'doit',
            'message': 'Download this episode?',
            'default': False,
        }
    ]
    for anime in config['monitored']:
        if not anime['monitored']:
            continue
        print("[yellow]Looking for missing episodes of " + anime['full_name'])
        basedir = config['base_directory'] + '/' + gen_basedir(anime)
        try:
            adl = AnimeRush(anime['url'], quality=config['quality'],
                            fallback_qualities=config['fallback_qualities'])
        except IndexError:
            adl = []
        for ep in adl:
            ep_num = int(ep.ep_no) + anime['season_offset']
            if have_episode(anime, ep_num, basedir):
                continue
            print("[red]Missing Episode {} of {}".format(str(ep_num),
                                                         anime['full_name']))
            fullpath = gen_fullname(anime, config['base_directory'], ep_num)

            if ask:
                answer = prompt(q_download)
                if answer['doit']:
                    print("[bold green]Downloading episode {} of {}".format(str(ep_num), anime['full_name']))
                    try:
                        ep.download(path=fullpath)
                    except a_exceptions.NotFoundError:
                        print("[bold red]Episode Missing!")
                    except u_errors.HTTPError as e:
                        if e.code > 400:
                            print("[bold red]Download error! {}".format(str(e.code)))
            else:
                print("[bold green]Downloading episode {} of {}".format(str(ep_num), anime['full_name']))
                try:
                    ep.download(path=fullpath)
                except a_exceptions.NotFoundError:
                    print("[bold red]Episode Missing!")
                except u_errors.HTTPError as e:
                    if e.code > 400:
                        print("[bold red]Download error! {}".format(str(e.code)))


def catch_up_single_anime(config, ask):
    """Catch up on a single anime"""

    # make a list
    alist = []
    for anime in config['monitored']:
        if not anime['monitored']:
            continue
        alist.append(anime['full_name'])

    q_which = [
        {
            'type': 'list',
            'name': 'selected',
            'message': 'Catch up on which anime?',
            'choices': alist,
        }
    ]

    q_download = [
        {
            'type': 'confirm',
            'name': 'doit',
            'message': 'Download this episode?',
            'default': False,
        }
    ]
    a_which = prompt(q_which)
    anime = find_anime_in_monitored_list(a_which['selected'], config['monitored'])
    print("[yellow]Looking for missing episodes of " + anime['full_name'])
    basedir = config['base_directory'] + '/' + gen_basedir(anime)
    try:
        adl = AnimeRush(anime['url'], quality=config['quality'],
                        fallback_qualities=config['fallback_qualities'])
    except IndexError:
            adl = []

    for ep in adl:
        ep_num = int(ep.ep_no) + anime['season_offset']
        if have_episode(anime, ep_num, basedir):
            continue
        print("[red]Missing Episode {} of {}".format(str(ep_num),
                                                     anime['full_name']))
        fullpath = gen_fullname(anime, config['base_directory'], ep_num)
        fullsdir = basedir + '/' + gen_seasondir(anime) + '/'

        if ask:
            answer = prompt(q_download)
            if answer['doit']:
                print("[bold green]Downloading episode {} of {}".format(str(ep_num), anime['full_name']))
                # external_download('{aria2}',
                #                   ep,
                #                   gen_epname(anime, ep.ep_no),
                #                   0,
                #                   path=fullsdir)
                try:
                    ep.download(path=fullpath)
                except a_exceptions.NotFoundError:
                    print("[bold red]Episode Missing!")
                except u_errors.HTTPError as e:
                    if e.code > 400:
                        print("[bold red]Download error! {}".format(str(e.code)))

        else:
            print("[bold green]Downloading episode {} of {}".format(str(ep_num), anime['full_name']))
            try:
                ep.download(path=fullpath)
            except a_exceptions.NotFoundError:
                print("[bold red]Episode Missing!")
            except u_errors.HTTPError as e:
                if e.code > 400:
                    print("[bold red]Download error! {}".format(str(e.code)))


def main():
    args = parse_args()

    config = parse_config(args.conffile)
    if config is None and not args.pick_anime:
        print('[red]No Config file found, create one with -p option')
        exit(1)

    if not args.pick_anime:
        config = fix_config(config, args.conffile)

    if args.new_anime_check:
        have_new = new_anime_check(config)
        if have_new:
            print('There is new anime to monitor')
            print('Run with the -p option to update conf file')
            exit(0)
        exit(1)

    if args.pick_anime:
        config = pick_anime(config, args.directory)
        with open(args.conffile, 'w') as file:
            yaml.dump(config, file)
        print('[green]Created/updated config file ' + args.conffile)
        exit(0)

    if args.initial_download_all:
        catch_up_all_anime(config, args.ask_initial)
        exit(0)

    if args.single_initial_download:
        catch_up_single_anime(config, args.ask_initial)
        exit(0)

    # fall down to default operation
    # get RSS, check monitored anime, and download.
    grabbed = parse_rss(config)
    if grabbed > 0:
        print("[green]Grabed {} new episodes".format(str(grabbed)))
    else:
        print("[bold green]No new episodes of monitored anime to download")
    have_new = new_anime_check(config)
    if have_new:
        print('There is new anime to monitor')
        print('Run with the -p option to update conf file')

if __name__ == '__main__':
    main()
