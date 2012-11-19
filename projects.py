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
from flask import Flask, Markup, abort, render_template_string
from flask.helpers import locked_cached_property
from flask.ext.babel import Babel
from mercurial import hg, ui as _ui
import os
import re

template = u"""\
<!DOCTYPE html>
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <title>{% if project %}{{ project.project_name }}{%
            else %}My Projects{% endif %}</title>
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
            #list-projects table {
                font-family: 'Kreon', serif;
                font-size: 20px;
                margin: 40px auto;
                padding: 0;
            }
            #list-projects th, #list-projects td {
                text-align: left;
                padding: 2px 15px;
            }
            #list-projects table th {
                font-size: 28px;
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
            else %}My Projects{% endif %}</h1>
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
            <table>
                {%- for project in projects %}
                <tr>
                    <th><a href="{{ url_for('show_project',
                        project=project.project_name) }}">{{
                        project.project_name }}</a></th>
                    <td>{% if project.description %}{{
                        project.description|truncate(80) }}{%
                        else %}&nbsp;{% endif %}</td>
                </tr>
                {%- endfor %}
            </table>
        </div>
        {%- endif %}
        <hr>
        <div id="footer">
            &copy;2012. Rafael G. Martins. Web pages generated automatically
            from my <a href="http://hg.rafaelmartins.eng.br/">Mercurial
            repositories</a>.
        </div>
    </body>
</html>
"""

# I'm picky about versions :P
re_version = re.compile(r'^([0-9]+)\.([0-9]+)(\.([0-9]+))?$')

app = Flask(__name__)
babel = Babel(app)

app.config.from_envvar('PROJECTS_SETTINGS', True)
app.config.setdefault('TIMEZONE', 'UTC')
app.config.setdefault('REPO_BASEDIR', '/home/rafael/dev/mercurial/pub')
app.config.setdefault('DIST_BASEDIR', '/home/rafael/dev/files')
app.config.setdefault('REPO_BASEURL', 'http://hg.rafaelmartins.eng.br')
app.config.setdefault('DIST_BASEURL', 'http://distfiles.rafaelmartins.eng.br')


@app.before_first_request
def before_first_request():
    app.projects = Project.from_all_repositories(app.config['REPO_BASEDIR'],
                                                 app.config['REPO_BASEURL'],
                                                 app.config['DIST_BASEDIR'],
                                                 app.config['DIST_BASEURL'])


@app.before_request
def before_request():
    projects = app.projects.keys()[:]
    for project in projects:
        if not app.projects[project].up2date:
            app.projects[project] = app.projects[project].update()


@babel.timezoneselector
def get_timezone():
    return app.config['TIMEZONE']


class Project(object):
    """Main object, that represents a single project"""

    def __init__(self, project_name, repo_basedir, repo_baseurl, dist_basedir,
                 dist_baseurl, ui=None):
        self.project_name = project_name
        self.repo_basedir = repo_basedir
        self.repo_baseurl = repo_baseurl
        self.dist_basedir = dist_basedir
        self.dist_baseurl = dist_baseurl
        self.ui = ui or _ui.ui()
        self.ui.setconfig('ui', 'report_untrusted', 'off')
        if not os.path.isdir(os.path.join(self.repo_path, '.hg')):
            return
        hgrc = os.path.join(self.repo_path, '.hg', 'hgrc')
        if os.path.isfile(hgrc):
            self.ui.readconfig(hgrc, trust=True)
        self.repo = hg.repository(self.ui, self.repo_path)
        default_branch = None
        branches = self.repo.branchtags()
        if 'default' in branches:
            default_branch = branches['default']
        self.default_ctx = self.repo[default_branch]  # use default branch

    @property
    def up2date(self):
        repo = hg.repository(self.ui, self.repo_path)
        default_branch = None
        branches = repo.branchtags()
        if 'default' in branches:
            default_branch = branches['default']
        ctx = repo[default_branch]
        return ctx.rev() == self.default_ctx.rev()

    @locked_cached_property
    def enabled(self):
        return self.ui.configbool('project', 'enabled', default=False,
                                  untrusted=True)

    @locked_cached_property
    def repo_path(self):
        return os.path.join(self.repo_basedir, self.project_name)

    @locked_cached_property
    def repo_url(self):
        return self.repo_baseurl.rstrip('/') + '/' + self.project_name

    @locked_cached_property
    def description(self):
        desc = self.ui.config('project', 'description', untrusted=True)
        if desc is None:
            desc = self.ui.config('web', 'description', untrusted=True)
        return desc

    @locked_cached_property
    def homepage(self):
        return self.ui.config('project', 'homepage', untrusted=True)

    @locked_cached_property
    def license(self):
        return self.ui.config('project', 'license', untrusted=True)

    @locked_cached_property
    def versions(self):
        versions = []
        for version, version_hash in self.repo.tagslist():
            if not re_version.match(version):
                continue
            # look for distfile
            distfile = None
            distfile_url = None
            for extension in ['tar.xz', 'tar.bz2', 'tar.gz']:
                _distfile = os.path.join(self.dist_basedir, self.project_name,
                                         '%s-%s.%s' % (self.project_name,
                                                       version, extension))
                if os.path.isfile(_distfile):
                    distfile = _distfile
                    break
            if distfile:
                distfile_url = self.dist_baseurl.rstrip('/') + '/' + \
                    self.project_name + '/' + os.path.basename(distfile)
            version_timestamp = self.repo[version_hash].date()[0]
            version_date = datetime.utcfromtimestamp(version_timestamp)
            versions.append((version, version_date, distfile_url))
        return versions

    @locked_cached_property
    def readme(self):
        # look for an usable README file. README.rst is preferred, but some
        # projects may have README too. in any case this file should be written
        # in reStructuredText.
        fctx = None
        for readme in ['README.rst', 'README']:
            if readme in self.default_ctx:
                fctx = self.default_ctx[readme]
                break
        if fctx is None:
            return
        settings = {'input_encoding': 'utf-8', 'output_encoding': 'utf-8',
                    'initial_header_level': 2}
        parts = publish_parts(source=fctx.data(), writer_name='html4css1',
                              settings_overrides=settings)
        return {'title': Markup(parts['title']),
                'fragment': Markup(parts['fragment'])}

    @classmethod
    def from_all_repositories(cls, repo_basedir, repo_baseurl, dist_basedir,
                              dist_baseurl, ui=None):
        rv = OrderedDict()
        for project_name in os.listdir(repo_basedir):
            obj = cls(project_name, repo_basedir, repo_baseurl,
                      dist_basedir, dist_baseurl, ui=None)
            if obj.enabled:
                rv[project_name] = obj
        return rv

    def update(self):
        return self.__class__(self.project_name, self.repo_basedir,
                              self.repo_baseurl, self.dist_basedir,
                              self.dist_baseurl, self.ui)

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.project_name)


@app.route('/')
def main():
    return render_template_string(template, projects=app.projects.values())


@app.route('/<project>/')
def show_project(project):
    project = app.projects.get(project)
    if project is None:
        abort(404)
    return render_template_string(template, project=project)


if __name__ == '__main__':
    app.run(debug=True)
