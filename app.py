# Python imports
import logging
import os

# Tornado imports
import tornado.auth
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web

from tornado.options import define, options
from tornado.web import url

import mongoengine
import yaml

# App imports
import forms
import importer
import models
import uimodules

# Options
define("port", default=8888, type=int)
define("config_file", default="app_config.yml", help="app_config file")

class Application(tornado.web.Application):
  def __init__(self):
    handlers = [
      url(r'/', IndexHandler, name='index'),
      url(r'/auth/google', GoogleAuthHandler, name='auth_google'),
      url(r'/logout', LogoutHandler, name='logout'),
      url(r'/home', HomeHandler, name='home'),
      url(r'/import', ImportHandler, name='import'),
      url(r'/edit/(?P<id>\w+)', EditBookmarkHandler, name='edit'),
      url(r'/new', NewBookmarkHandler, name='new'),
    ]
    settings = dict(
      debug=self.config.debug,
      login_url='/auth/google',
      static_path=os.path.join(os.path.dirname(__file__), "static"),
      template_path=os.path.join(os.path.dirname(__file__), 'templates'),
      xsrf_cookies=True,
      cookie_secret=self.config.cookie_secret,
      ui_modules=uimodules,
    )
    tornado.web.Application.__init__(self, handlers, **settings)
    mongoengine.connect(self.config.mongodb_database)

  @property
  def config(self):
    if not hasattr(self, '_config'):
      logging.debug("Loading app config")
      stream = file(options.config_file, 'r')
      self._config = tornado.web._O(yaml.load(stream))
    return self._config


class BaseHandler(tornado.web.RequestHandler):
  def get_current_user(self):
    user_id = self.get_secure_cookie('user_id')
    if not user_id:
      return None
    return models.User.objects(id=user_id).first()


class IndexHandler(BaseHandler):
  def get(self):
    form = forms.HelloForm()
    self.render('index.html', form=form)

  def post(self):
    form = forms.HelloForm(self)
    if form.validate():
      self.write('Hello %s' % form.planet.data)
    else:
      self.render('index.html', form=form)


class GoogleAuthHandler(BaseHandler, tornado.auth.GoogleMixin):
  @tornado.web.asynchronous
  def get(self):
    if self.get_argument('openid.mode', None):
      self.get_authenticated_user(self.async_callback(self._on_auth))
      return
    self.authenticate_redirect()

  def _on_auth(self, guser):
    if not guser:
      raise tornado.web.HTTPError(500, "Google auth failed")

    user = models.User.objects(email=guser['email']).first()
    if user is None:
      user = models.User(email=guser['email'], name=guser['name'])
      user.save()
    self.set_secure_cookie('user_id', str(user.id))
    self.redirect(self.reverse_url('home'))


class LogoutHandler(BaseHandler):
  def get(self):
    self.clear_cookie('user_id')
    self.redirect(self.reverse_url('home'))


class HomeHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    bookmarks = models.Bookmark.objects.filter(user=self.current_user)[:25]
    self.render('home.html', bookmarks=bookmarks)


class ImportHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    self.render('import.html')

  @tornado.web.authenticated
  def post(self):
    file = self.request.files.get('file')[0]
    importer.Importer(self.current_user, file['body']).import_bookmarks()
    self.redirect(self.reverse_url('home'))


class EditBookmarkHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self, id):
    try:
      bookmark = models.Bookmark.objects.get(user=self.current_user, id=id)
    except models.Bookmark.DoesNotExist:
      raise tornado.web.HTTPError(404)
    form = forms.BookmarkForm(obj=bookmark)
    self.render('edit.html', form=form)

  @tornado.web.authenticated
  def post(self, id):
    try:
      bookmark = models.Bookmark.objects.get(user=self.current_user, id=id)
    except models.Bookmark.DoesNotExist:
      raise tornado.web.HTTPError(404)
    form = forms.BookmarkForm(self, obj=bookmark)
    if form.validate():
      form.populate_obj(bookmark)
      bookmark.save()
      self.redirect(self.reverse_url('home'))
    else:
      self.render('edit.html', form=form)


class NewBookmarkHandler(BaseHandler):
  @tornado.web.authenticated
  def get(self):
    form = forms.BookmarkForm()
    self.render('new.html', form=form)

  @tornado.web.authenticated
  def post(self):
    form = forms.BookmarkForm(self)
    if form.validate():
      bookmark = models.Bookmark(user=self.current_user)
      form.populate_obj(bookmark)
      bookmark.save()
      self.redirect(self.reverse_url('home'))
    else:
      self.render('new.html', form=form)


def main():
  tornado.options.parse_command_line()
  http_server = tornado.httpserver.HTTPServer(Application())
  http_server.listen(options.port)
  tornado.ioloop.IOLoop.instance().start()

if __name__ == '__main__':
  main()
