import os
import errno
import six
import random
import time
import datetime
import logging
import string
import requests
from bs4 import BeautifulSoup as BeautifulSoup_
from xml.sax.saxutils import unescape
from six import iteritems
from six.moves import html_parser
from six.moves.urllib.parse import ParseResult
from six.moves.urllib_parse import unquote_plus
from define import COURSERA_URL

BeautifulSoup = lambda page: BeautifulSoup_(page, 'html.parser')

# Python3 (and six) don't provide string
if six.PY3:
    from string import ascii_letters as string_ascii_letters
    from string import digits as string_digits
else:
    from string import letters as string_ascii_letters
    from string import digits as string_digits

if six.PY3:  # pragma: no cover
    from urllib.parse import urlparse, urljoin
else:
    from urlparse import urlparse, urljoin


# Taken from: https://wiki.python.org/moin/EscapingHtml
# escape() and unescape() takes care of &, < and >.
HTML_ESCAPE_TABLE = {
    '"': "&quot;",
    "'": "&apos;"
}

HTML_UNESCAPE_TABLE = dict((v, k) for k, v in HTML_ESCAPE_TABLE.items())


def unescape_html(s):
    h = html_parser.HTMLParser()
    s = h.unescape(s)
    s = unquote_plus(s)
    return unescape(s, HTML_UNESCAPE_TABLE)


def clean_filename(s, minimal_change=False):
    """
    Sanitize a string to be used as a filename.
    If minimal_change is set to true, then we only strip the bare minimum of
    characters that are problematic for filesystems (namely, ':', '/' and
    '\x00', '\n').
    """

    # First, deal with URL encoded strings
    h = html_parser.HTMLParser()
    s = h.unescape(s)
    s = unquote_plus(s)

    # Strip forbidden characters
    s = (
        s.replace(':', '-')
        .replace('/', '-')
        .replace('\x00', '-')
        .replace('\n', '')
    )

    if minimal_change:
        return s

    s = s.replace('(', '').replace(')', '')
    s = s.rstrip('.')  # Remove excess of trailing dots

    s = s.strip().replace(' ', '_')
    valid_chars = '-_.()%s%s' % (string.ascii_letters, string.digits)
    return ''.join(c for c in s if c in valid_chars)


def clean_url(url):
    """
    Remove params, query and fragment parts from URL so that `os.path.basename`
    and `os.path.splitext` can work correctly.
    @param url: URL to clean.
    @type url: str
    @return: Cleaned URL.
    @rtype: str
    """
    parsed = urlparse(url.strip())
    reconstructed = ParseResult(
        parsed.scheme, parsed.netloc, parsed.path,
        params='', query='', fragment='')
    return reconstructed.geturl()


def extend_supplement_links(destination, source):
    """
    Extends (merges) destination dictionary with supplement_links
    from source dictionary. Values are expected to be lists, or any
    data structure that has `extend` method.
    @param destination: Destination dictionary that will be extended.
    @type destination: @see CourseraOnDemand._extract_links_from_text
    @param source: Source dictionary that will be used to extend
        destination dictionary.
    @type source: @see CourseraOnDemand._extract_links_from_text
    """
    for key, value in iteritems(source):
        if key not in destination:
            destination[key] = value
        else:
            destination[key].extend(value)


def is_course_complete(last_update):
    """
    Determine is the course is likely to have been terminated or not.
    We return True if the timestamp given by last_update is 30 days or older
    than today's date.  Otherwise, we return True.
    The intended use case for this is to detect if a given courses has not
    seen any update in the last 30 days or more.  Otherwise, we return True,
    since it is probably too soon to declare the course complete.
    """
    rv = False
    if last_update >= 0:
        delta = time.time() - last_update
        max_delta = total_seconds(datetime.timedelta(days=30))
        if delta > max_delta:
            rv = True
    return rv


def is_debug_run():
    """
    Check whether we're running with DEBUG loglevel.
    @return: True if running with DEBUG loglevel.
    @rtype: bool
    """
    return logging.getLogger().isEnabledFor(logging.DEBUG)


def make_coursera_absolute_url(url):
    """
    If given url is relative adds coursera netloc,
    otherwise returns it without any changes.
    """

    if not bool(urlparse(url).netloc):
        return urljoin(COURSERA_URL, url)

    return url


def mkdir_p(path, mode=0o777):
    """
    Create subditrctory hierarchy given in the paths argument
    """

    try:
        os.makedirs(path, mode)
        """
        Recursive directory creation function. Like mkdir(), but makes all
        intermediate-level directories needed to contain the leaf directory.
        The mode parameter is passed to mkdir().
        If exist_ok is False (the default), an OSError is raised
        if the target directory already exists.
        """
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def random_string(length):
    """
    Return a pseudo-random string of specified length.
    """
    valid_chars = string_ascii_letters + string_digits

    return ''.join(random.choice(valid_chars) for i in range(length))


def total_seconds(td):
    """
    Compute total seconds for a timedelta.
    Added for backward compatibility, pre 2.7.
    """
    return (td.microseconds +
            (td.seconds + td.days * 24 * 3600) * 10 ** 6) // 10 ** 6


def get_reply(session, url, post=False, data=None, headers=None):
    """
    Download an HTML page using the requests session. Low-level function
    that allows for flexible request configuration.
    @param session: Requests session.
    @type session: requests.Session
    @param url: URL pattern with optional keywords to format.
    @type url: str
    @param post: Flag that indicates whether POST request should be sent.
    @type post: bool
    @param data: Payload data that is sent with request (in request body).
    @type data: object
    @param headers: Additional headers to send with request.
    @type headers: dict
    @return: Requests response.
    @rtype: requests.Response
    """

    request_headers = {} if headers is None else headers

    request = requests.Request('POST' if post else 'GET',
                               url,
                               data=data,
                               headers=request_headers)
    prepared_request = session.prepare_request(request)

    reply = session.send(prepared_request)

    try:
        reply.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logging.error("Error %s getting page %s", e, url)
        logging.error("The server replied: %s", reply.text)
        raise

    return reply


def get_page(session,
             url,
             json=False,
             post=False,
             data=None,
             headers=None,
             **kwargs):
    """
    Download an HTML page using the requests session.
    """
    url = url.format(**kwargs)
    reply = get_reply(session, url, post=post, data=data, headers=headers)
    return reply.json() if json else reply.text
