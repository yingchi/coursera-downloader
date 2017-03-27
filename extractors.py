import requests
import logging
import json
from abc import ABCMeta, abstractmethod
from cookies import login
from api import CourseraOnDemand, OnDemandCourseMaterialItems


OPENCOURSE_CONTENT_URL = 'https://www.coursera.org/api/opencourse.v1/course/{class_name}?showLockedItems=true'

# test url: https://www.coursera.org/api/opencourse.v1/course/principles-of-macroeconomics


class PlatformExtractor(metaclass=ABCMeta):
    """
    Define the behavior or any class inherent from this
    """
    @abstractmethod
    def get_modules(self):
        """
        Get course modeuls.
        """
        pass


class CourseraExtractor(PlatformExtractor):
    def __init__(self, session, email, password):
        login(session, email, password)

        self._session = session

    def list_courses(self):
        """
        List enrolled courses.
        """
        course = CourseraOnDemand(session=self._session,
                                  course_id=None,
                                  course_name=None)
        return course.list_courses()

    def get_modules(self, class_name,
                    reverse=False, unrestricted_filenames=False,
                    subtitle_language='en', video_resolution=None,
                    download_quizzes=True):
        page = self._get_on_demand_syllabus(class_name)
        error_occured, modules = self._parse_on_demand_syllabus(
            page, reverse, unrestricted_filenames,
            subtitle_language, video_resolution,
            download_quizzes)
        return error_occured, modules

    def _get_on_demand_syllabus(self, class_name):
        """
        Get the on-demand course listing webpage.
        """

        url = OPENCOURSE_CONTENT_URL.format(class_name=class_name)
        page = get_page(self._session, url)
        logging.info('Downloaded %s (%d bytes)', url, len(page))

        return page

    def _parse_on_demand_syllabus(self, page, reverse=False,
                                  unrestricted_filenames=False,
                                  subtitle_language='en',
                                  video_resolution=None,
                                  download_quizzes=False):
        """
        Parse a Coursera on-demand course listing/syllabus page.
        @return: Tuple of (bool, list), where bool indicates whether
            there was at least on error while parsing syllabus, the list
            is a list of parsed modules.
        @rtype: (bool, list)
        """

        dom = json.loads(page)
        course_name = dom['slug']

        logging.info('Parsing syllabus of on-demand course. '
                     'This may take some time, please be patient ...')
        modules = []
        json_modules = dom['courseMaterial']['elements']
        course = CourseraOnDemand(session=self._session, course_id=dom['id'],
                                  course_name=course_name,
                                  unrestricted_filenames=unrestricted_filenames)
        course.obtain_user_id()
        ondemand_material_items = OnDemandCourseMaterialItems.create(
            session=self._session, course_name=course_name)

        error_occured = False

        for module in json_modules:
            module_slug = module['slug']
            logging.info('Processing module  %s', module_slug)
            sections = []
            json_sections = module['elements']
            for section in json_sections:
                section_slug = section['slug']
                logging.info('Processing section     %s', section_slug)
                lectures = []
                json_lectures = section['elements']

                # Certain modules may be empty-looking programming assignments
                # e.g. in data-structures, algorithms-on-graphs ondemand courses
                if not json_lectures:
                    lesson_id = section['id']
                    lecture = ondemand_material_items.get(lesson_id)
                    if lecture is not None:
                        json_lectures = [lecture]

                for lecture in json_lectures:
                    lecture_slug = lecture['slug']
                    typename = lecture['content']['typeName']

                    logging.info('Processing lecture         %s (%s)',
                                 lecture_slug, typename)
                    # Empty dictionary means there were no data
                    # None means an error occured
                    links = {}

                    if typename == 'lecture':
                        lecture_video_id = lecture['content']['definition']['videoId']
                        assets = lecture['content']['definition'].get('assets', [])

                        links = course.extract_links_from_lecture(
                            lecture_video_id, subtitle_language,
                            video_resolution, assets)

                    elif typename == 'supplement':
                        links = course.extract_links_from_supplement(
                            lecture['id'])

                    elif typename in ('gradedProgramming', 'ungradedProgramming'):
                        links = course.extract_links_from_programming(lecture['id'])

                    elif typename == 'quiz':
                        if download_quizzes:
                            links = course.extract_links_from_quiz(lecture['id'])

                    elif typename == 'exam':
                        if download_quizzes:
                            links = course.extract_links_from_exam(lecture['id'])

                    else:
                        logging.info('Unsupported typename "%s" in lecture "%s"',
                                     typename, lecture_slug)
                        continue

                    if links is None:
                        error_occured = True
                    elif links:
                        lectures.append((lecture_slug, links))

                if lectures:
                    sections.append((section_slug, lectures))

            if sections:
                modules.append((module_slug, sections))

        if modules and reverse:
            modules.reverse()

        return error_occured, modules


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
