#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# projects - A simple flask app to create homepages for projects, based on info
#            gathered from mercurial repositories.
#
# (c) 2012 Rafael G. Martins <rafael@rafaelmartins.eng.br>
#
# Released under the terms of the GNU General Public License, Version 2.
# <http://www.gnu.org/licenses/gpl-2.0.txt>

from collections import OrderedDict
from datetime import datetime, timedelta
from docutils.core import publish_parts
from flask import Flask, Markup, abort, render_template_string
from flask.helpers import locked_cached_property
from flask.ext.babel import Babel
from mercurial import hg, ui
import os
import re

template = u"""\
<!DOCTYPE html>
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <title>{% if project %}{{ project.pid }}{%
            else %}Rafael Martins' Projects{% endif %}</title>
        <link href="http://fonts.googleapis.com/css?family=Kreon:400,700"
              rel="stylesheet" type="text/css">
        <link href="http://fonts.googleapis.com/css?family=Droid+Sans:400,700"
              rel="stylesheet" type="text/css">
        <style type="text/css">
            * {
                margin: 0;
                padding: 0;
            }
            body {
                font-family: "Droid Sans", sans-serif;
                background-color: #FFF;
                color: #000;
            }
            a {
                color: #036;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            h1, h2, h3, h4, h5, h6 {
                font-family: 'Kreon', serif;
            }
            h1, h2, h3 {
                text-align: center;
            }
            h1 {
                font-size: 46px;
                margin: 20px auto;
            }
            h2 {
                font-size: 28px;
                margin: 16px auto;
            }
            h3 {
                font-size: 24px;
                margin: 10px auto;
            }
            p {
                margin: 16px auto;
            }
            ul {
                padding-left: 20px;
                padding-bottom: 16px;
            }
            #list-projects ul, #list-projects li {
                font-family: 'Kreon', serif;
                text-align: center;
                list-style: none;
                font-size: 28px;
            }
            #list-projects ul {
                margin: 40px auto;
                padding: 0;
            }
            #list-projects li {
                margin: 15px auto;
            }
            #project table {
                margin: 16px auto;
                margin-bottom: 34px;
            }
            #project th, #project td {
                text-align: left;
                padding: 2px 20px;
            }
            #readme {
                width: 700px;
                text-align: justify;
                margin: 20px auto;
                margin-bottom: 34px;
                padding: 0 16px;
                border: 1px dashed #ccc;
            }
            #footer {
                text-align: center;
                margin: 10px auto;
            }
        </style>
    </head>
    <body>
        <h1>{% if project %}{{ project.pid }}{%
            else %}Rafael Martins' Projects{% endif %}</h1>
        {%- if project %}
        <div id="project">
            <table>
                {%- if project.description %}
                <tr>
                    <th>Description:</th>
                    <td>{{ project.description }}</td>
                </tr>
                {%- endif %}
                {%- if project.homepage %}
                <tr>
                    <th>Homepage:</th>
                    <td><a href="{{ project.homepage }}">{{
                        project.homepage }}</a></td>
                </tr>
                {%- endif %}
                <tr>
                    <th>Mercurial repository:</th>
                    <td><a href="{{ project.repo_url }}">{{
                        project.repo_url }}</a></td>
                </tr>
                {% if project.license %}
                <tr>
                    <th>License:</th>
                    <td>{{ project.license }}</td>
                </tr>
                {%- endif %}
            </table>
            {%- if project.versions %}
            <h2>Recent releases</h2>
            <table>
                <tr>
                    <th>Version</th>
                    <th>Date</th>
                    <th>Download</th>
                </tr>
                {%- for version, date, download in
                    project.versions[-5:]|reverse %}
                <tr>
                    <td>{{ version }}</td>
                    <td>{{ date|datetimeformat }}</td>
                    <td>{% if download %}<a href="{{
                        download }}">Download</a>{% else %}&nbsp;{%
                        endif %}</td>
                </tr>
                {%- endfor %}
            </table>
            {%- endif %}
            {%- if project.readme %}
            <h2>README</h2>
            <div id="readme">
                <h3>{{ project.readme.title }}</h3>
                {{ project.readme.fragment }}
            </div>
            {%- endif %}
        </div>
        {%- else %}
        <div id="list-projects">
            <ul>
                {%- for project in projects %}
                <li><a href="{{ url_for('show_project', pid=project) }}">{{
                    project }}</a></li>
                {%- endfor %}
            </ul>
        </div>
        {%- endif %}
        <hr>
        <div id="footer">
            &copy 2012. Rafael G. Martins. Web pages generated automatically
            from my <a href="http://hg.rafaelmartins.eng.br/">Mercurial
            repositories</a>.<br />Cache date: {{ cache_date|datetimeformat }}.
        </div>
    </body>
</html>
"""

# I'm picky about versions :P
re_version = re.compile(r'^([0-9]+)\.([0-9]+)(\.([0-9]+))?$')

app = Flask(__name__)
babel = Babel(app)

app.config.from_envvar('PROJECTS_SETTINGS', True)
app.config.setdefault('CACHE_TIMEOUT', 60)  # in minutes
app.config.setdefault('TIMEZONE', 'UTC')
app.config.setdefault('REPO_BASEDIR', '/home/rafael/dev/mercurial/pub')
app.config.setdefault('DIST_BASEDIR', '/home/rafael/dev/files')
app.config.setdefault('REPO_BASEURL', 'http://hg.rafaelmartins.eng.br')
app.config.setdefault('DIST_BASEURL', 'http://distfiles.rafaelmartins.eng.br')


@app.before_request
def before_request():
    # validate cache
    if hasattr(app, 'projects_cache_date'):
        delta = timedelta(minutes=float(app.config['CACHE_TIMEOUT']))
        if app.projects_cache_date + delta > datetime.now():
            return

    # reload projects
    app.projects = Project.from_all_repositories()
    app.projects_cache_date = datetime.now()


@babel.timezoneselector
def get_timezone():
    return app.config['TIMEZONE']


@app.context_processor
def jinja_ctx():
    return {'cache_date': app.projects_cache_date}


def find_repositories(basedir):
    for i in os.listdir(basedir):
        f = os.path.join(basedir, i)
        if os.path.isdir(f):  # just directories can be repositories :P
            if os.path.exists(os.path.join(f, '.hg')):  # is a repo!
                yield f[len(basedir) + 1:]


class Project(object):
    """Main object, that represents a single project"""

    def __init__(self, pid):
        self.pid = pid
        self.ui = ui.ui()
        self.ui.setconfig('ui', 'report_untrusted', 'off')
        self.repo = hg.repository(self.ui, self.path)
        hgrc = os.path.join(self.path, '.hg', 'hgrc')
        if os.path.exists(hgrc):
            self.ui.readconfig(hgrc, Trust=True)
        self.ctx = self.repo[None]

    @locked_cached_property
    def enabled(self):
        return self.ui.configbool('project', 'enabled', untrusted=True)

    @locked_cached_property
    def path(self):
        return os.path.join(app.config['REPO_BASEDIR'], self.pid)

    @locked_cached_property
    def repo_url(self):
        return app.config['REPO_BASEURL'].rstrip('/') + '/' + self.pid

    @locked_cached_property
    def description(self):
        rv = self.ui.config('project', 'description', untrusted=True)
        if rv is None:  # defaults to hgweb description
            rv = self.ui.config('web', 'description', untrusted=True)
        return rv

    @locked_cached_property
    def homepage(self):
        return self.ui.config('project', 'homepage', untrusted=True)

    @locked_cached_property
    def license(self):
        return self.ui.config('project', 'license', untrusted=True)

    @locked_cached_property
    def versions(self):
        return [(i[0], datetime.utcfromtimestamp(self.repo[i[1]].date()[0]),
                 self.get_distfile_url(i[0])) for i in self.repo.tagslist()
                if re_version.match(i[0])]

    @locked_cached_property
    def readme(self):
        # look for an usable README file. README.rst is preferred, but some
        # projects may have README too. in any case this file should be written
        # in reStructuredText.
        fctx = None
        for i in ['README.rst', 'README']:
            if i in self.ctx:
                fctx = self.ctx[i]
                break
        if fctx is None:
            return
        rst = fctx.data()
        settings = {'input_encoding': 'utf-8', 'output_encoding': 'utf-8',
                    'initial_header_level': 2}
        parts = publish_parts(source=rst, writer_name='html4css1',
                              settings_overrides=settings)
        return {'title': Markup(parts['title']),
                'fragment': Markup(parts['fragment'])}

    def get_distfile(self, version):

        def get_from_ext(ext):
            distfile = os.path.join(app.config['DIST_BASEDIR'], self.pid,
                                    '%s-%s.%s' % (self.pid, version, ext))
            if os.path.exists(distfile):
                return distfile

        for ext in ['tar.xz', 'tar.bz2', 'tar.gz']:
            distfile = get_from_ext(ext)
            if distfile is not None:
                return distfile

    def get_distfile_url(self, version):
        distfile = self.get_distfile(version)
        if distfile is None:
            return
        return app.config['DIST_BASEURL'].rstrip('/') + '/' + self.pid + '/' \
            + os.path.basename(distfile)

    @classmethod
    def from_all_repositories(cls):
        rv = OrderedDict()
        for pid in sorted(find_repositories(app.config['REPO_BASEDIR'])):
            obj = cls(pid)
            if obj.enabled:
                rv[pid] = obj
            else:
                del obj
        return rv

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.pid)


@app.route('/')
def main():
    return render_template_string(template, projects=app.projects)


@app.route('/<pid>/')
def show_project(pid):
    project = app.projects.get(pid)
    if project is None:
        abort(404)
    return render_template_string(template, project=project)


if __name__ == '__main__':
    app.run(debug=True)
