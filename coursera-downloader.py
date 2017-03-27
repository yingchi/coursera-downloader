"""
Module for downloading lecture resources such as videos for Coursera classes.
Given a class name, username and password, it scrapes the course listing
page to get the section (week) and lecture names, and then downloads the
related materials into appropriately named files and directories.
To run:
    python coursera-downloader.py

The original project's home at:
  https://github.com/coursera-dl/coursera
"""

import os
import sys
import json
import shutil
import logging
import requests
from authpass import clearScreen, createPass, getUserPass
from cookies import AuthenticationFailed, ClassNotFound, TLSAdapter
from extractors import CourseraExtractor
from downloaders import get_downloader, ConsecutiveDownloader, CourseraDownloader

# ---- Definition ---- #
# define a per-user cache folder
import getpass
import tempfile

if os.name == "posix":  # pragma: no cover
    import pwd
    _USER = pwd.getpwuid(os.getuid())[0]
else:
    _USER = getpass.getuser()

PATH_CACHE = os.path.join(tempfile.gettempdir(), _USER + "_coursera_cache")
PATH_COOKIES = os.path.join(PATH_CACHE, 'cookies')
# -------------


class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


default_args = {'file_formats': 'all', 'lecture_filter': None,
                'resource_filter': None, 'resource_filter': None,
                'verbose_dir': False, 'combined-section-lectures-nums': False,
                'playlist': False, 'hooks': [],
                'path': '/Users/PeiYingchi/Documents/GitHub/coursera-downloader/downloaded',
                'disable-url-skipping': False,
                'overwrite': False, 'resume': False,
                'skip-download': False}

default_args = dotdict(default_args)


def clearCache():
    clear_flag = str(input('Want to clear your coursera downloader cache? [y/n] '))
    if clear_flag == 'y':
        shutil.rmtree(PATH_CACHE)


def download_class(email, password, class_name):
    """
    Download all requested resources from the on-demand class given in class_name.
    @return: Tuple of (bool, bool), where the first bool indicates whether
        errors occured while parsing syllabus, the second bool indicaters
        whether the course appears to be completed.
    @rtype: (bool, bool)
    """
    error_occured = False
    session = get_session()
    extractor = CourseraExtractor(session, email, password)

    cached_syllabus_filename = '%s-syllabus-parsed.json' % class_name
    cache_syllabus = str(input('Cache syllabus? [y/n] '))
    cache_syllabus = True if cache_syllabus == 'y' else False

    if cache_syllabus and os.path.isfile(cached_syllabus_filename):
        with open(cached_syllabus_filename) as syllabus_file:
            modules = json.load(syllabus_file)
    else:
        error_occured, modules = extractor.get_modules(class_name)

    if cache_syllabus:
        with open(cached_syllabus_filename, 'w') as file_object:
            json.dump(modules, file_object, indent=4)

    downloader_bin = str(input('Choose downloader type: \nrecommend: curl or axel\n'))
    downloader = get_downloader(session, class_name, downloader_bin)
    downloader_wrapper = ConsecutiveDownloader(downloader)

    ignore_formats = []
    ignore_formats = str(input('Which format files you want to ignore?\n e.g.: "mp4, pdf, xlsx, txt, srt, html"\n'))
    ignored_formats = ignore_formats.split(",")

    course_downloader = CourseraDownloader(
        downloader_wrapper,
        commandline_args=default_args,
        class_name=class_name,
        path=default_args.path,
        ignored_formats=ignored_formats,
        disable_url_skipping=default_args.disable_url_skipping
    )
    completed = course_downloader.download_modules(modules)

    return error_occured, completed


def get_session():
    """
    Create a session with TLS v1.2 certificate
    """

    session = requests.Session()
    session.mount('https://', TLSAdapter())

    return session


def list_courses(email, password):
    """
    List enrolled courses.
    """
    session = get_session()
    extractor = CourseraExtractor(session, email, password)
    courses = extractor.list_courses()
    logging.info('Found %d courses', len(courses))
    for course in courses:
        logging.info(course)
    return courses


def main():
    """
    Main entry point for execution as a program
    """

    global email, password, fullCourseName, default_args
    clearScreen()

    try:
        email, password = getUserPass('coursera.pass')
    except OSError:
        print('FileNotFound\n')
        createPass()
        print('User and password has been saved to coursera.pass file.\n')
        print('Please delete the file if you want to change your credentials')
        email, password = getUserPass('coursera.pass')

    clearCache()
    logging.info('Listing enrolled courses')
    courses = list_courses(email, password)

    for i in range(0, len(courses)):
        print("["+str(i+1)+"] " + courses[i])

    print("\n")
    while True:
        sys.stdout.write("[  ] Please pick course number!\r")
        pick = input("[")[:2]
        sys.stdout.write("[  ] second message!\r")
        try:
            pick = int(pick)
            break
        except:
            continue

    class_name = courses[pick-1]
    print("\nYou have chosen: ["+str(pick)+"] " + class_name + "\n")

    try:
        logging.info('Downloading class: %s', class_name)
        error_occured, completed = download_class(email, password, class_name)
        if completed:
            logging.info('Download complete')
        if error_occured:
            logging.info('Error occurred')
    except requests.exceptions.HTTPError as e:
        logging.error('HTTPError %s', e)
    except requests.exceptions.SSLError as e:
        logging.error('SSLError %s', e)
    except ClassNotFound as cnf:
        logging.error('Could not find class: %s', cnf)
    except AuthenticationFailed as af:
        logging.error('Could not authenticate: %s', af)


if __name__ == '__main__':
    main()
