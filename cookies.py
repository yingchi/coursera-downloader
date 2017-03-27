import ssl
import logging
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
from utils import random_string


CLASS_URL = 'https://class.coursera.org/{class_name}'
AUTH_URL = 'https://accounts.coursera.org/api/v1/login'
AUTH_URL_V3 = 'https://www.coursera.org/api/login/v3'

class ClassNotFound(BaseException):
    """
    Raised if a course is not found in Coursera's site.
    """


class AuthenticationFailed(BaseException):
    """
    Raised if we cannot authenticate on Coursera's site.
    """


def prepape_auth_headers(session, include_cauth=False):
    """
    This function prepapes headers with CSRF/CAUTH tokens that can
    be used in POST requests such as login/get_quiz.
    @param session: Requests session.
    @type session: requests.Session
    @param include_cauth: Flag that indicates whethe CAUTH cookies should be
        included as well.
    @type include_cauth: bool
    @return: Dictionary of headers.
    @rtype: dict
    """

    # csrftoken is simply a 20 char random string
    csrftoken = random_string(20)

    # now make a call to the authenticator url
    csrf2cookie = 'csrf2_token_%s' % random_string(8)
    csrf2token = random_string(24)
    cookie = "csrftoken=%s; %s=%s" % (csrftoken, csrf2cookie, csrf2token)

    if include_cauth:
        CAUTH = session.cookies.get('CAUTH')
        cookie = "CAUTH=%s; %s" % (CAUTH, cookie)

    logging.debug('Forging cookie header: %s.', cookie)
    headers = {
        'Cookie': cookie,
        'X-CSRFToken': csrftoken,
        'X-CSRF2-Cookie': csrf2cookie,
        'X-CSRF2-Token': csrf2token
    }

    return headers


def login(session, email, password, class_name=None):
    """
    Login on coursera.org with the given credentials.
    This adds the following cookies to the session:
        sessionid, maestro_login, maestro_login_flag
    """
    logging.debug('Initiating login...')
    try:
        session.cookies.clear('.coursera.org')
        logging.debug('Cleared .coursera.org cookies.')
    except KeyError:
        logging.debug('There were no .coursera.org cookies to be cleared.')

    # Hit class url
    if class_name is not None:
        class_url = CLASS_URL.format(class_name=class_name)
        r = requests.get(class_url)
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logging.error(e)
            raise ClassNotFound(class_name)

    headers = prepape_auth_headers(session, include_cauth=False)

    data = {
        'email': email,
        'password': password,
        'webrequest': 'true'
    }

    # Auth API V3
    r = session.post(AUTH_URL_V3, data=data,
                     headers=headers, allow_redirects=False)
    try:
        r.raise_for_status()

        # Some how the order of cookies parameters are important
        # for coursera!!!
        v = session.cookies.pop('CAUTH')
        session.cookies.set('CAUTH', v)
    except requests.exceptions.HTTPError as e:
        raise AuthenticationFailed('Cannot login on coursera.org: %s' % e)

    logging.info('Logged in on coursera.org.')


class TLSAdapter(HTTPAdapter):
    """
    A customized HTTP Adapter which uses TLS v1.2 for encrypted connections.
    HTTPAdapter has default values as the following:
    pool_connections=10, pool_maxsize=10, max_retries=0, pool_block=False
    """
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       ssl_version=ssl.PROTOCOL_TLSv1)
