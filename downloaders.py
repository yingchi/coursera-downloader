import logging
import math
import os
import subprocess
import sys
import time
import requests
import abc
import codecs
import traceback
import re

from six import iteritems
from utils import is_course_complete, mkdir_p
from formatting import format_section, get_lecture_filename
from filtering import find_resources_to_get, skip_format_url

#
# Below are file downloaders, they are wrappers for external downloaders.
#

IN_MEMORY_MARKER = '#inmemory#'


class Downloader(object):
    """
    Base downloader class.
    Every subclass should implement the _start_download method.
    Usage::
      >>> import downloaders
      >>> d = downloaders.SubclassFromDownloader()
      >>> d.download('http://example.com', 'save/to/this/file')
    """

    def _start_download(self, url, filename, resume):
        """
        Actual method to download the given url to the given file.
        This method should be implemented by the subclass.
        """
        raise NotImplementedError("Subclasses should implement this")

    def download(self, url, filename, resume=False):
        """
        Download the given url to the given file. When the download
        is aborted by the user, the partially downloaded file is also removed.
        """

        try:
            self._start_download(url, filename, resume)
        except KeyboardInterrupt as e:
            # keep the file if resume is True
            if not resume:
                logging.info('Keyboard Interrupt -- Removing partial file: %s',
                             filename)
                try:
                    os.remove(filename)
                except OSError:
                    pass
            raise e


class ExternalDownloader(Downloader):
    """
    Downloads files with an external downloader.
    We could possibly use python to stream files to disk,
    but this is slow compared to these external downloaders.
    :param session: Requests session.
    :param bin: External downloader binary.
    """

    # External downloader binary
    bin = None

    def __init__(self, session, bin=None, downloader_arguments=None):
        self.session = session
        self.bin = bin or self.__class__.bin
        self.downloader_arguments = downloader_arguments or []

        if not self.bin:
            raise RuntimeError("No bin specified")

    def _prepare_cookies(self, command, url):
        """
        Extract cookies from the requests session and add them to the command
        """

        req = requests.models.Request()
        req.method = 'GET'
        req.url = url

        cookie_values = requests.cookies.get_cookie_header(
            self.session.cookies, req)

        if cookie_values:
            self._add_cookies(command, cookie_values)

    def _enable_resume(self, command):
        """
        Enable resume feature
        """

        raise RuntimeError("Subclass should implement this")

    def _add_cookies(self, command, cookie_values):
        """
        Add the given cookie values to the command
        """

        raise RuntimeError("Subclasses should implement this")

    def _create_command(self, url, filename):
        """
        Create command to execute in a subprocess.
        """
        raise NotImplementedError("Subclasses should implement this")

    def _start_download(self, url, filename, resume):
        command = self._create_command(url, filename)
        command.extend(self.downloader_arguments)
        self._prepare_cookies(command, url)
        if resume:
            self._enable_resume(command)

        logging.debug('Executing %s: %s', self.bin, command)
        try:
            subprocess.call(command)
        except OSError as e:
            msg = "{0}. Are you sure that '{1}' is the right bin?".format(
                e, self.bin)
            raise OSError(msg)


class WgetDownloader(ExternalDownloader):
    """
    Uses wget, which is robust and gives nice visual feedback.
    """

    bin = 'wget'

    def _enable_resume(self, command):
        command.append('-c')

    def _add_cookies(self, command, cookie_values):
        command.extend(['--header', "Cookie: " + cookie_values])

    def _create_command(self, url, filename):
        return [self.bin, url, '-O', filename, '--no-cookies',
                '--no-check-certificate']


class CurlDownloader(ExternalDownloader):
    """
    Uses curl, which is robust and gives nice visual feedback.
    """

    bin = 'curl'

    def _enable_resume(self, command):
        command.extend(['-C', '-'])

    def _add_cookies(self, command, cookie_values):
        command.extend(['--cookie', cookie_values])

    def _create_command(self, url, filename):
        return [self.bin, url, '-k', '-#', '-L', '-o', filename]


class AxelDownloader(ExternalDownloader):
    """
    Uses axel, which is robust and it both gives nice
    visual feedback and get the job done fast.
    """

    bin = 'axel'

    def _enable_resume(self, command):
        logging.warn('Resume download not implemented for this '
                     'downloader!')

    def _add_cookies(self, command, cookie_values):
        command.extend(['-H', "Cookie: " + cookie_values])

    def _create_command(self, url, filename):
        return [self.bin, '-o', filename, '-n', '4', '-a', url]


def format_bytes(bytes):
    """
    Get human readable version of given bytes.
    Ripped from https://github.com/rg3/youtube-dl
    """
    if bytes is None:
        return 'N/A'
    if type(bytes) is str:
        bytes = float(bytes)
    if bytes == 0.0:
        exponent = 0
    else:
        exponent = int(math.log(bytes, 1024.0))
    suffix = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'][exponent]
    converted = float(bytes) / float(1024 ** exponent)
    return '{0:.2f}{1}'.format(converted, suffix)


class DownloadProgress(object):
    """
    Report download progress.
    Inspired by https://github.com/rg3/youtube-dl
    """

    def __init__(self, total):
        if total in [0, '0', None]:
            self._total = None
        else:
            self._total = int(total)

        self._current = 0
        self._start = 0
        self._now = 0

        self._finished = False

    def start(self):
        self._now = time.time()
        self._start = self._now

    def stop(self):
        self._now = time.time()
        self._finished = True
        self._total = self._current
        self.report_progress()

    def read(self, bytes):
        self._now = time.time()
        self._current += bytes
        self.report_progress()

    def report(self, bytes):
        self._now = time.time()
        self._current = bytes
        self.report_progress()

    def calc_percent(self):
        if self._total is None:
            return '--%'
        if self._total == 0:
            return '100% done'
        percentage = int(float(self._current) / float(self._total) * 100.0)
        done = int(percentage / 2)
        return '[{0: <50}] {1}%'.format(done * '#', percentage)

    def calc_speed(self):
        dif = self._now - self._start
        if self._current == 0 or dif < 0.001:  # One millisecond
            return '---b/s'
        return '{0}/s'.format(format_bytes(float(self._current) / dif))

    def report_progress(self):
        """Report download progress."""
        percent = self.calc_percent()
        total = format_bytes(self._total)

        speed = self.calc_speed()
        total_speed_report = '{0} at {1}'.format(total, speed)

        report = '\r{0: <56} {1: >30}'.format(percent, total_speed_report)

        if self._finished:
            print(report)
        else:
            print(report)
        sys.stdout.flush()


class NativeDownloader(Downloader):
    """
    'Native' python downloader -- slower than the external downloaders.
    :param session: Requests session.
    """

    def __init__(self, session):
        self.session = session

    def _start_download(self, url, filename, resume=False):
        # resume has no meaning if the file doesn't exists!
        resume = resume and os.path.exists(filename)

        headers = {}
        filesize = None
        if resume:
            filesize = os.path.getsize(filename)
            headers['Range'] = 'bytes={}-'.format(filesize)
            logging.info('Resume downloading %s -> %s', url, filename)
        else:
            logging.info('Downloading %s -> %s', url, filename)

        max_attempts = 3
        attempts_count = 0
        error_msg = ''
        while attempts_count < max_attempts:
            r = self.session.get(url, stream=True, headers=headers)

            if r.status_code != 200:
                # because in resume state we are downloading only a
                # portion of requested file, server may return
                # following HTTP codes:
                # 206: Partial Content
                # 416: Requested Range Not Satisfiable
                # which are OK for us.
                if resume and r.status_code == 206:
                    pass
                elif resume and r.status_code == 416:
                    logging.info('%s already downloaded', filename)
                    r.close()
                    return True
                else:
                    print('%s %s %s' % (r.status_code, url, filesize))
                    logging.warn('Probably the file is missing from the AWS '
                                 'repository...  waiting.')

                    if r.reason:
                        error_msg = r.reason + ' ' + str(r.status_code)
                    else:
                        error_msg = 'HTTP Error ' + str(r.status_code)

                    wait_interval = 2 ** (attempts_count + 1)
                    msg = 'Error downloading, will retry in {0} seconds ...'
                    print(msg.format(wait_interval))
                    time.sleep(wait_interval)
                    attempts_count += 1
                    continue

            if resume and r.status_code == 200:
                # if the server returns HTTP code 200 while we are in
                # resume mode, it means that the server does not support
                # partial downloads.
                resume = False

            content_length = r.headers.get('content-length')
            chunk_sz = 1048576
            progress = DownloadProgress(content_length)
            progress.start()
            f = open(filename, 'ab') if resume else open(filename, 'wb')
            while True:
                data = r.raw.read(chunk_sz, decode_content=True)
                if not data:
                    progress.stop()
                    break
                progress.report(r.raw.tell())
                f.write(data)
            f.close()
            r.close()
            return True

        if attempts_count == max_attempts:
            logging.warn('Skipping, can\'t download file ...')
            logging.error(error_msg)
            return False


class AbstractDownloader(object):
    """
    Base class for download wrappers. Two methods should be implemented:
    `download` and `join`.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, file_downloader):
        super(AbstractDownloader, self).__init__()
        self._file_downloader = file_downloader

    @abc.abstractmethod
    def download(self, *args, **kwargs):
        raise NotImplementedError()

    @abc.abstractmethod
    def join(self):
        raise NotImplementedError()

    def _download_wrapper(self, url, *args, **kwargs):
        """
        Actual download call. Calls the underlying file downloader,
        catches all exceptions and returns the result.
        """
        try:
            return url, self._file_downloader.download(url, *args, **kwargs)
        except Exception as e:
            logging.error("AbstractDownloader: %s", traceback.format_exc())
            return url, e


class ConsecutiveDownloader(AbstractDownloader):
    """
    This class calls underlying file downloader in a sequential order
    in the same thread where it was created.
    """
    def download(self, callback, url, *args, **kwargs):
        _, result = self._download_wrapper(url, *args, **kwargs)
        callback(url, result)
        return result

    def join(self):
        pass


def _iter_modules(modules, class_name, path, ignored_formats, args):
    """
    This huge function generates a hierarchy with hopefully more
    clear structure of modules/sections/lectures.
    """
    file_formats = args.file_formats
    lecture_filter = args.lecture_filter
    resource_filter = args.resource_filter
    section_filter = args.section_filter
    verbose_dirs = args.verbose_dirs
    combined_section_lectures_nums = args.combined_section_lectures_nums

    class IterModule(object):
        def __init__(self, index, module):
            self.index = index
            self.name = '%02d_%s' % (index + 1, module[0])
            self._module = module

        @property
        def sections(self):
            sections = self._module[1]
            for (secnum, (section, lectures)) in enumerate(sections):
                if section_filter and not re.search(section_filter, section):
                    logging.debug('Skipping b/c of sf: %s %s',
                                  section_filter, section)
                    continue

                yield IterSection(self, secnum, section, lectures)

    class IterSection(object):
        def __init__(self, module_iter, secnum, section, lectures):
            self.index = secnum
            self.name = '%02d_%s' % (secnum, section)
            self.dir = os.path.join(
                path, class_name, module_iter.name,
                format_section(secnum + 1, section,
                               class_name, verbose_dirs))
            self._lectures = lectures

        @property
        def lectures(self):
            for (lecnum, (lecname, lecture)) in enumerate(self._lectures):
                if lecture_filter and not re.search(lecture_filter, lecname):
                    logging.debug('Skipping b/c of lf: %s %s',
                                  lecture_filter, lecname)
                    continue

                yield IterLecture(self, lecnum, lecname, lecture)

    class IterLecture(object):
        def __init__(self, section_iter, lecnum, lecname, lecture):
            self.index = lecnum
            self.name = lecname
            self._lecture = lecture
            self._section_iter = section_iter

        def filename(self, fmt, title):
            lecture_filename = get_lecture_filename(
                combined_section_lectures_nums,
                self._section_iter.dir, self._section_iter.index,
                self.index, self.name, title, fmt)
            return lecture_filename

        @property
        def resources(self):
            resources_to_get = find_resources_to_get(
                self._lecture, file_formats, resource_filter,
                ignored_formats)

            for fmt, url, title in resources_to_get:
                yield IterResource(fmt, url, title)

    class IterResource(object):
        def __init__(self, fmt, url, title):
            self.fmt = fmt
            self.url = url
            self.title = title

    for index, module in enumerate(modules):
        yield IterModule(index, module)


class CourseDownloader(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        pass

    @abc.abstractmethod
    def download_modules(self, modules):
        pass


class CourseraDownloader(CourseDownloader):
    def __init__(self,
                 downloader,
                 commandline_args,
                 class_name,
                 path='',
                 ignored_formats=None,
                 disable_url_skipping=False):
        super(CourseraDownloader, self).__init__()

        self._downloader = downloader
        self._args = commandline_args
        self._class_name = class_name
        self._path = path
        self._ignored_formats = ignored_formats
        self._disable_url_skipping = disable_url_skipping

        self.skipped_urls = None if disable_url_skipping else []
        self.failed_urls = []

    def download_modules(self, modules):
        completed = True
        modules = _iter_modules(
            modules, self._class_name, self._path,
            self._ignored_formats, self._args)

        for module in modules:
            last_update = -1
            for section in module.sections:
                if not os.path.exists(section.dir):
                    mkdir_p(section.dir)

                for lecture in section.lectures:
                    for resource in lecture.resources:
                        lecture_filename = lecture.filename(resource.fmt, resource.title)
                        last_update = self._handle_resource(
                            resource.url, resource.fmt, lecture_filename,
                            self._download_completion_handler, last_update)

            # if we haven't updated any files in 1 month, we're probably
            # done with this course
            completed = completed and is_course_complete(last_update)

        if completed:
            logging.info('COURSE PROBABLY COMPLETE: ' + self._class_name)

        # Wait for all downloads to complete
        self._downloader.join()
        return completed

    def _download_completion_handler(self, url, result):
        if isinstance(result, requests.exceptions.RequestException):
            logging.error('The following error has occurred while '
                          'downloading URL %s: %s', url, str(result))
            self.failed_urls.append(url)
        elif isinstance(result, Exception):
            logging.error('Unknown exception occurred: %s', result)
            self.failed_urls.append(url)

    def _handle_resource(self, url, fmt, lecture_filename, callback, last_update):
        """
        Handle resource. This function builds up resource file name and
        downloads it if necessary.
        @param url: URL of the resource.
        @type url: str
        @param fmt: Format of the resource (pdf, csv, etc)
        @type fmt: str
        @param lecture_filename: File name of the lecture.
        @type lecture_filename: str
        @param callback: Callback that will be called when file has been
            downloaded. It will be called even if exception occurred.
        @type callback: callable(url, result) where result may be Exception
        @param last_update: Timestamp of the newest file so far.
        @type last_update: int
        @return: Updated latest mtime.
        @rtype: int
        """
        overwrite = self._args.overwrite
        resume = self._args.resume
        skip_download = self._args.skip_download

        # Decide whether we need to download it
        if overwrite or not os.path.exists(lecture_filename) or resume:
            if not skip_download:
                if url.startswith(IN_MEMORY_MARKER):
                    page_content = url[len(IN_MEMORY_MARKER):]
                    logging.info('Saving page contents to: %s', lecture_filename)
                    with codecs.open(lecture_filename, 'w', 'utf-8') as file_object:
                        file_object.write(page_content)
                else:
                    if self.skipped_urls is not None and skip_format_url(fmt, url):
                        self.skipped_urls.append(url)
                    else:
                        logging.info('Downloading: %s', lecture_filename)
                        self._downloader.download(callback, url, lecture_filename, resume=resume)
            else:
                open(lecture_filename, 'w').close()  # touch
            last_update = time.time()
        else:
            logging.info('%s already downloaded', lecture_filename)
            # if this file hasn't been modified in a long time,
            # record that time
            last_update = max(last_update,
                              os.path.getmtime(lecture_filename))
        return last_update


def get_downloader(session, class_name, downloader_bin):
    """
    Decides which downloader to use.
    """

    external = {
        'wget': WgetDownloader,
        'curl': CurlDownloader,
        'axel': AxelDownloader,
    }

    for bin, class_ in iteritems(external):
        if bin == downloader_bin:
            return class_(session)

    return NativeDownloader(session)
