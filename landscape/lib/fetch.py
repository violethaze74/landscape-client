import os
import sys

from optparse import OptionParser
from StringIO import StringIO

import pycurl

from twisted.internet.threads import deferToThread
from twisted.internet.defer import DeferredList


class FetchError(Exception):
    pass


class HTTPCodeError(FetchError):

    def __init__(self, http_code, body):
        self.http_code = http_code
        self.body = body

    def __str__(self):
        return "Server returned HTTP code %d" % self.http_code

    def __repr__(self):
        return "<HTTPCodeError http_code=%d>" % self.http_code


class PyCurlError(FetchError):

    def __init__(self, error_code, message):
        self.error_code = error_code
        self._message = message

    def __str__(self):
        return "Error %d: %s" % (self.error_code, self.message)

    def __repr__(self):
        return "<PyCurlError args=(%d, '%s')>" % (self.error_code,
                                                  self.message)

    @property
    def message(self):
        return self._message


def fetch(url, post=False, data="", headers={}, cainfo=None, curl=None,
          connect_timeout=30, total_timeout=600):
    """Retrieve a URL and return the content.

    @param url: The url to be fetched.
    @param post: If true, the POST method will be used (defaults to GET).
    @param data: Data to be sent to the server as the POST content.
    @param headers: Dictionary of header => value entries to be used
                    on the request.
    @param cainfo: Path to the file with CA certificates.
    """
    output = StringIO(data)
    input = StringIO()

    if curl is None:
        curl = pycurl.Curl()

    if post:
        curl.setopt(pycurl.POST, True)

        if data:
            curl.setopt(pycurl.POSTFIELDSIZE, len(data))
            curl.setopt(pycurl.READFUNCTION, output.read)

    if cainfo and url.startswith("https:"):
        curl.setopt(pycurl.CAINFO, cainfo)

    if headers:
        curl.setopt(pycurl.HTTPHEADER,
                    ["%s: %s" % pair for pair in sorted(headers.iteritems())])

    curl.setopt(pycurl.URL, url)
    curl.setopt(pycurl.FOLLOWLOCATION, True)
    curl.setopt(pycurl.MAXREDIRS, 5)
    curl.setopt(pycurl.CONNECTTIMEOUT, connect_timeout)
    curl.setopt(pycurl.LOW_SPEED_LIMIT, 1)
    curl.setopt(pycurl.LOW_SPEED_TIME, total_timeout)
    curl.setopt(pycurl.NOSIGNAL, 1)
    curl.setopt(pycurl.WRITEFUNCTION, input.write)

    try:
        curl.perform()
    except pycurl.error, e:
        raise PyCurlError(e.args[0], e.args[1])

    body = input.getvalue()

    http_code = curl.getinfo(pycurl.HTTP_CODE)
    if http_code != 200:
        raise HTTPCodeError(http_code, body)

    return body


def test(args):
    parser = OptionParser()
    parser.add_option("--post", action="store_true")
    parser.add_option("--data", default="")
    parser.add_option("--cainfo")
    options, (url,) = parser.parse_args(args)
    print fetch(url, post=options.post, data=options.data,
                cainfo=options.cainfo)


def fetch_async(*args, **kwargs):
    """Retrieve a URL asynchronously.

    @return: A C{Deferred} resulting in the URL content.
    """
    return deferToThread(fetch, *args, **kwargs)


def fetch_many_async(urls, callback=None, errback=None, **kwargs):
    """
    Retrieve a list of URLs asynchronously.

    @param callback: Optionally, a function that will be fired one time for
        each successful URL, and will be passed its content and the URL itself.
    @param errback: Optionally, a function that will be fired one time for each
        failing URL, and will be passed the failure and the URL itself.
    @return: A C{DeferredList} whose callback chain will be fired as soon as
        all downloads have terminated. If an error occurs, the errback chain
        of the C{DeferredList} will be fired immediatly.
    """
    results = []
    for url in urls:
        result = fetch_async(url, **kwargs)
        if callback:
            result.addCallback(callback, url)
        if errback:
            result.addErrback(errback, url)
        results.append(result)
    return DeferredList(results, fireOnOneErrback=True, consumeErrors=True)


def fetch_to_files(urls, directory, logger=None, **kwargs):
    """
    Retrieve a list of URLs and save their content as files in a directory.

    @param urls: The list URLs to fetch.
    @param directory: The directory to save the files to, the name of the file
        will equal the last fragment of the URL.
    @param logger: Optional function to be used to log errors for failed URLs.
    """

    def write(data, url):
        filename = os.path.join(directory, url.rstrip("/").split("/")[-1])
        fd = open(filename, "w")
        fd.write(data)
        fd.close()

    def log_error(failure, url):
        if logger:
            logger("Couldn't fetch file from %s (%s)" % (
                url, str(failure.value)))
        return failure

    return fetch_many_async(urls, callback=write, errback=log_error, **kwargs)


if __name__ == "__main__":
    test(sys.argv[1:])
