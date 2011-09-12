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

import yaml
import pymongo

import tornado.web
from tornado.options import define, options
define("config_file", default="app_config.yml", help="app_config file")


class Retriever(object):
  def __init__(self):
    self.conn = pymongo.Connection()
    self.db = self.conn[self.config.mongodb_database]

  @property
  def config(self):
    if not hasattr(self, '_config'):
      logging.debug("Loading app config")
      stream = file(options.config_file, 'r')
      self._config = tornado.web._O(yaml.load(stream))
    return self._config

  def run(self):
    logging.info("Retriever started")
    while True:
      task = self.db.tasks.find_one()
      if task is None:
        logging.info("Task queue is currently empty.")
      logging.info("Sleeping for 1 second")
      time.sleep(1)


def main():
  tornado.options.parse_command_line()
  retriever = Retriever()
  retriever.run()

if __name__ == '__main__':
  main()
