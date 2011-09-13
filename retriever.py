import sys
import pycurl
import logging
import time

# We should ignore SIGPIPE when using pycurl.NOSIGNAL - see
# the libcurl tutorial for more info.
try:
  import signal
  from signal import SIGPIPE, SIG_IGN
  signal.signal(signal.SIGPIPE, signal.SIG_IGN)
except ImportError:
  pass

from cStringIO import StringIO

import yaml
import pymongo
from pymongo.objectid import ObjectId

import tornado.web
from tornado.options import define, options
define("config_file", default="app_config.yml", help="app_config file")


class Retriever(object):
  def __init__(self):
    self.conn = pymongo.Connection()
    self.db = self.conn[self.config.mongodb_database]
    num_conn = 10

    # Initialize curl objects
    curl = pycurl.CurlMulti()
    curl.handles = []
    for i in range(num_conn):
      c = pycurl.Curl()
      c.fp = None
      c.setopt(pycurl.FOLLOWLOCATION, 1)
      c.setopt(pycurl.MAXREDIRS, 5)
      c.setopt(pycurl.CONNECTTIMEOUT, 30)
      c.setopt(pycurl.TIMEOUT, 300)
      c.setopt(pycurl.NOSIGNAL, 1)
      curl.handles.append(c)
    self.curl = curl

  @property
  def config(self):
    if not hasattr(self, '_config'):
      logging.debug("Loading app config")
      stream = file(options.config_file, 'r')
      self._config = tornado.web._O(yaml.load(stream))
    return self._config

  def run(self):
    logging.info("Retriever started")
    freelist = self.curl.handles[:]

    while True:
      queue = list(self.db.tasks.find(limit=20))

      while queue and freelist:
        task = queue.pop(0)
        url = task['url']
        user = task['user']
        bookmark = task['bookmark']
        self.db.tasks.remove(task['_id'])

        c = freelist.pop()
        c.fp = StringIO()
        c.setopt(pycurl.URL, url.encode('utf8'))
        c.setopt(pycurl.WRITEFUNCTION, c.fp.write)
        self.curl.add_handle(c)
        c.url = url
        c.bookmark = bookmark
        c.user = user

        logging.info("Added %s to the queue" % c.url)

      while 1:
        ret, num_handles = self.curl.perform()
        if ret != pycurl.E_CALL_MULTI_PERFORM:
          break

      while 1:
        num_q, ok_list, err_list = self.curl.info_read()
        for c in ok_list:
          c.fp.close()
          c.fp = None
          self.curl.remove_handle(c)
          # Update bookmark
          dct = {'status': 200}
          if c.getinfo(pycurl.EFFECTIVE_URL) != c.url:
            dct['redirects'] = c.getinfo(pycurl.EFFECTIVE_URL)
          self.db.bookmarks.update({'url_digest': c.bookmark, 'user': c.user},
                                   {'$set': dct})
          freelist.append(c)
        for c, errno, errmsg in err_list:
          c.fp.close()
          c.fp = None
          self.curl.remove_handle(c)
          dct = {'status': errno, 'errormsg': errmsg}
          self.db.bookmarks.update({'url_digest': c.bookmark, 'user': c.user},
                                   {'$set': dct})
          freelist.append(c)
        if num_q == 0:
          break

      self.curl.select(1.0)
      time.sleep(2)


def main():
  tornado.options.parse_command_line()
  retriever = Retriever()
  retriever.run()

if __name__ == '__main__':
  main()
