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
from datetime import datetime
from docutils.core import publish_parts
from flask import Flask, Markup, abort, g, render_template_string
from flask.helpers import locked_cached_property
from flask.ext.babel import Babel
from mercurial import hg, ui
from werkzeug.contrib.cache import FileSystemCache
import os
import re

template = u"""\
<!DOCTYPE html>
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <title>{% if project %}{{ project.project_name }}{%
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
        <h1>{% if project %}{{ project.project_name }}{%
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
                <li><a href="{{ url_for('show_project', project=project) }}">{{
                    project }}</a></li>
                {%- endfor %}
            </ul>
        </div>
        {%- endif %}
        <hr>
        <div id="footer">
            &copy 2012. Rafael G. Martins. Web pages generated automatically
            from my <a href="http://hg.rafaelmartins.eng.br/">Mercurial
            repositories</a>.<br />Cache date: {{ cache_date|datetimeformat }}
        </div>
    </body>
</html>
"""

# I'm picky about versions :P
re_version = re.compile(r'^([0-9]+)\.([0-9]+)(\.([0-9]+))?$')

app = Flask(__name__)
babel = Babel(app)

app.config.from_envvar('PROJECTS_SETTINGS', True)
app.config.setdefault('CACHE_DIR', '/tmp/projects')
app.config.setdefault('CACHE_TIMEOUT', 3600)  # in seconds
app.config.setdefault('TIMEZONE', 'UTC')
app.config.setdefault('REPO_BASEDIR', '/home/rafael/dev/mercurial/pub')
app.config.setdefault('DIST_BASEDIR', '/home/rafael/dev/files')
app.config.setdefault('REPO_BASEURL', 'http://hg.rafaelmartins.eng.br')
app.config.setdefault('DIST_BASEURL', 'http://distfiles.rafaelmartins.eng.br')


def generate_cache():
    """This function handles all the expensive operations that involves the
    Mercurial API, directory lookups and rst parsing, returning a big dict
    suitable for caching.

    Dict format::

        {
            "projects": {
                "a": {
                    "homepage": "http://foo.com",
                    "versions": [
                        ("1", datetime(...), "/home/foo/files/a-1.tar.gz"),
                        ...
                    ],
                    ...
                },
                ...
            },
            "cache_date": datetime(...),
        }
    """
    base_ui = ui.ui()  # our base ui, will be copied by each project
    base_ui.setconfig('ui', 'report_untrusted', 'off')
    rv = {'projects': {}, 'cache_date': datetime.now()}
    for project_name in os.listdir(app.config['REPO_BASEDIR']):
        project_dir = os.path.join(app.config['REPO_BASEDIR'], project_name)
        if not os.path.exists(os.path.join(project_dir, '.hg')):  # not a repo!
            continue
        project_ui = base_ui.copy()
        project_hgrc = os.path.join(project_dir, '.hg', 'hgrc')
        if os.path.exists(project_hgrc):
            project_ui.readconfig(project_hgrc, trust=True)
        project_repo = hg.repository(project_ui, project_dir)
        if not project_ui.configbool('project', 'enabled', untrusted=True):
            continue
        rv['projects'][project_name] = \
            dict(project_ui.configitems('project', untrusted=True))
        if 'description' not in rv['projects'][project_name]:
            rv['projects'][project_name]['description'] = \
                project_ui.config('web', 'description')
        rv['projects'][project_name]['versions'] = []
        # fill versions
        versions = []
        for version, version_hash in project_repo.tagslist():
            if not re_version.match(version):
                continue
            # look for distfile
            distfile = None
            distfile_url = None
            for extension in ['tar.xz', 'tar.bz2', 'tar.gz']:
                _distfile = os.path.join(app.config['DIST_BASEDIR'],
                                         project_name,
                                         '%s-%s.%s' % (project_name, version,
                                                       extension))
                if os.path.exists(_distfile):
                    distfile = _distfile
                    break
            if distfile:
                distfile_url = app.config['DIST_BASEURL'].rstrip('/') + '/' + \
                    project_name + '/' + os.path.basename(distfile)
            version_timestamp = project_repo[version_hash].date()[0]
            version_date = datetime.utcfromtimestamp(version_timestamp)
            versions.append((version, version_date, distfile_url))
        rv['projects'][project_name]['versions'] = versions
        # look for an usable README file. README.rst is preferred, but some
        # projects may have README too. in any case this file should be written
        # in reStructuredText.
        default_branch = None
        branches = project_repo.branchtags()
        if 'default' in branches:
            default_branch = branches['default']
        default_ctx = project_repo[default_branch]  # use default branch
        fctx = None
        for readme in ['README.rst', 'README']:
            if readme in default_ctx:
                fctx = default_ctx[readme]
                break
        readme = None
        if fctx:
            rst = fctx.data()
            settings = {'input_encoding': 'utf-8', 'output_encoding': 'utf-8',
                        'initial_header_level': 2}
            parts = publish_parts(source=rst, writer_name='html4css1',
                                  settings_overrides=settings)
            readme = {'title': Markup(parts['title']),
                      'fragment': Markup(parts['fragment'])}
        rv['projects'][project_name]['readme'] = readme
    return rv


@app.before_first_request
def before_first_request():
    # drop old cache when initializing the app
    g.cache_obj = FileSystemCache(app.config['CACHE_DIR'],
                                  default_timeout=app.config['CACHE_TIMEOUT'])
    cache = generate_cache()
    g.cache_obj.set('projects', cache)
    g.cache = cache
    g.projects = Project.from_all_repositories()


@app.before_request
def before_request():
    if hasattr(g, 'cache_obj'):  # already initialized
        return
    g.cache_obj = FileSystemCache(app.config['CACHE_DIR'],
                                  default_timeout=app.config['CACHE_TIMEOUT'])
    cache = g.cache_obj.get('projects')
    if cache is None:
        cache = generate_cache()
        g.cache_obj.set('projects', cache)
    g.cache = cache
    g.projects = Project.from_all_repositories()


@babel.timezoneselector
def get_timezone():
    return app.config['TIMEZONE']


@app.context_processor
def jinja_ctx():
    return {'cache_date': g.cache['cache_date']}


class Project(object):
    """Main object, that represents a single project"""

    def __init__(self, project_name):
        self.project_name = project_name

    @locked_cached_property
    def path(self):
        return os.path.join(app.config['REPO_BASEDIR'], self.project_name)

    @locked_cached_property
    def repo_url(self):
        return app.config['REPO_BASEURL'].rstrip('/') + '/' + self.project_name

    @locked_cached_property
    def description(self):
        return g.cache['projects'][self.project_name].get('description')

    @locked_cached_property
    def homepage(self):
        return g.cache['projects'][self.project_name].get('homepage')

    @locked_cached_property
    def license(self):
        return g.cache['projects'][self.project_name].get('license')

    @locked_cached_property
    def versions(self):
        return g.cache['projects'][self.project_name].get('versions')

    @locked_cached_property
    def readme(self):
        return g.cache['projects'][self.project_name].get('readme')

    @classmethod
    def from_all_repositories(cls):
        rv = OrderedDict()
        for project_name in sorted(g.cache['projects'].keys()):
            rv[project_name] = cls(project_name)
        return rv

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.project_name)


@app.route('/')
def main():
    return render_template_string(template, projects=g.projects)


@app.route('/<project>/')
def show_project(project):
    project = g.projects.get(project)
    if project is None:
        abort(404)
    return render_template_string(template, project=project)


if __name__ == '__main__':
    app.run(debug=True)
