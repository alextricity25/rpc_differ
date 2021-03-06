#!/usr/bin/env python
# Copyright 2016, Major Hayden
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Analyzes the differences between two OpenStack-Ansible commits."""
import argparse
import json
import os
import sys


from git import Repo
import jinja2
from osa_differ import osa_differ
import requests


def create_parser():
    """Setup argument Parsing."""
    description = """RPC Release Diff Generator
--------------------------

Finds changes in OpenStack-Ansible, OpenStack-Ansible roles, and OpenStack
projects between two RPC-OpenStack revisions.

"""

    parser = argparse.ArgumentParser(
        usage='%(prog)s',
        description=description,
        epilog='Licensed "Apache 2.0"',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'old_commit',
        action='store',
        nargs=1,
        help="Git SHA of the older commit",
    )
    parser.add_argument(
        'new_commit',
        action='store',
        nargs=1,
        help="Git SHA of the newer commit",
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help="Enable debug output",
    )
    parser.add_argument(
        '-d', '--directory',
        action='store',
        default="~/.osa-differ",
        help="Git repo storage directory (default: ~/.osa-differ)",
    )
    parser.add_argument(
        '-u', '--update',
        action='store_true',
        default=False,
        help="Fetch latest changes to repo",
    )
    display_opts = parser.add_argument_group("Limit scope")
    display_opts.add_argument(
        "--skip-projects",
        action="store_true",
        help="Skip checking for changes in OpenStack projects"
    )
    display_opts.add_argument(
        "--skip-roles",
        action="store_true",
        help="Skip checking for changes in OpenStack-Ansible roles"
    )
    output_desc = ("Output is printed to stdout by default.")
    output_opts = parser.add_argument_group('Output options', output_desc)
    output_opts.add_argument(
        '--quiet',
        action='store_true',
        default=False,
        help="Do not output to stdout",
    )
    output_opts.add_argument(
        '--gist',
        action='store_true',
        default=False,
        help="Output into a GitHub Gist",
    )
    output_opts.add_argument(
        '--file',
        metavar="FILENAME",
        action='store',
        help="Output to a file",
    )
    return parser


def get_osa_commits(repo_dir, old_commit, new_commit):
    """Get OSA commits from the RPC repository."""
    repo = Repo(repo_dir)

    repo.head.reference = repo.commit(old_commit)
    repo.head.reset(index=True, working_tree=True)
    old_osa_commit = repo.submodules['openstack-ansible'].hexsha

    repo.head.reference = repo.commit(new_commit)
    repo.head.reset(index=True, working_tree=True)
    new_osa_commit = repo.submodules['openstack-ansible'].hexsha

    return (old_osa_commit, new_osa_commit)


def make_rpc_report(repo_dir, old_commit, new_commit,
                    args):
    """Create initial RST report header for OpenStack-Ansible."""
    rpc_repo_url = "https://github.com/rcbops/rpc-openstack"
    osa_differ.update_repo(repo_dir, rpc_repo_url, args.update)

    # Are these commits valid?
    osa_differ.validate_commits(repo_dir, [old_commit, new_commit])

    # Do we have a valid commit range?
    osa_differ.validate_commit_range(repo_dir, old_commit, new_commit)

    # Get the commits in the range
    commits = osa_differ.get_commits(repo_dir, old_commit, new_commit)

    # Start off our report with a header and our OpenStack-Ansible commits.
    template_vars = {
        'args': args,
        'repo': 'rpc-openstack',
        'commits': commits,
        'commit_base_url': osa_differ.get_commit_url(rpc_repo_url),
        'old_sha': old_commit,
        'new_sha': new_commit
    }
    return render_template('offline-header.j2', template_vars)


def parse_arguments():
    """Parse arguments."""
    parser = create_parser()
    args = parser.parse_args()
    return args


def post_gist(report_data, old_sha, new_sha):
    """Post the report to a GitHub Gist and return the URL of the gist."""
    payload = {
        "description": ("Changes in RPC-OpenStack between "
                        "{0} and {1}".format(old_sha, new_sha)),
        "public": True,
        "files": {
            "rpc-diff-{0}-{1}.rst".format(old_sha, new_sha): {
                "content": report_data
            }
        }
    }
    url = "https://api.github.com/gists"
    r = requests.post(url, data=json.dumps(payload))
    response = r.json()
    return response['html_url']


def publish_report(report, args, old_commit, new_commit):
    """Publish the RST report based on the user request."""
    # Print the report to stdout unless the user specified --quiet.
    output = ""

    if not args.quiet and not args.gist and not args.file:
        return report

    if args.gist:
        gist_url = post_gist(report, old_commit, new_commit)
        output += "\nReport posted to GitHub Gist: {0}".format(gist_url)

    if args.file is not None:
        with open(args.file, 'w') as f:
            f.write(report)
        output += "\nReport written to file: {0}".format(args.file)

    return output


def render_template(template_file, template_vars):
    """Render a jinja template."""
    # Load our Jinja templates
    template_dir = "{0}/templates".format(
        os.path.dirname(os.path.abspath(__file__))
    )
    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        trim_blocks=True
    )
    rendered = jinja_env.get_template(template_file).render(template_vars)

    return rendered


def run_rpc_differ():
    """The script starts here."""
    args = parse_arguments()

    # Create the storage directory if it doesn't exist already.
    try:
        storage_directory = osa_differ.prepare_storage_dir(args.directory)
    except OSError:
        print("ERROR: Couldn't create the storage directory {0}. "
              "Please create it manually.".format(args.directory))
        sys.exit(1)

    # Assemble some variables for the RPC repository.
    rpc_old_commit = args.old_commit[0]
    rpc_new_commit = args.new_commit[0]
    rpc_repo_dir = "{0}/rpc-openstack".format(storage_directory)

    # Generate RPC report header.
    report_rst = make_rpc_report(rpc_repo_dir,
                                 rpc_old_commit,
                                 rpc_new_commit,
                                 args)

    # Get the list of RPC roles from the newer and older commits.
    role_yaml = osa_differ.get_roles(rpc_repo_dir, rpc_old_commit)
    role_yaml_latest = osa_differ.get_roles(rpc_repo_dir, rpc_new_commit)

    # Generate the role report.
    report_rst += ("RPC-OpenStack Roles\n"
                   "-------------------")
    report_rst += osa_differ.make_report(storage_directory,
                                         role_yaml,
                                         role_yaml_latest,
                                         args.update)

    report_rst += "\n"

    # Generate OpenStack-Ansible report.
    osa_old_commit, osa_new_commit = get_osa_commits(rpc_repo_dir,
                                                     rpc_old_commit,
                                                     rpc_new_commit)

    osa_repo_dir = "{0}/openstack-ansible".format(storage_directory)
    report_rst += osa_differ.make_osa_report(osa_repo_dir,
                                             osa_old_commit,
                                             osa_new_commit,
                                             args)

    # Get the list of OpenStack-Ansible roles from the newer and older commits.
    role_yaml = osa_differ.get_roles(osa_repo_dir, osa_old_commit)
    role_yaml_latest = osa_differ.get_roles(osa_repo_dir, osa_new_commit)

    # Generate the role report.
    report_rst += ("OpenStack-Ansible Roles\n"
                   "-----------------------")
    report_rst += osa_differ.make_report(storage_directory,
                                         role_yaml,
                                         role_yaml_latest,
                                         args.update)

    # Get the list of OpenStack projects from newer commit and older commit.
    yaml_files = [
        'playbooks/defaults/repo_packages/openstack_services.yml',
        'playbooks/defaults/repo_packages/openstack_other.yml'
    ]
    project_yaml = osa_differ.get_projects(osa_repo_dir,
                                           yaml_files,
                                           osa_old_commit)
    project_yaml_latest = osa_differ.get_projects(osa_repo_dir,
                                                  yaml_files,
                                                  osa_new_commit)

    # Generate the project report.
    report_rst += ("OpenStack-Ansible Projects\n"
                   "--------------------------")
    report_rst += osa_differ.make_report(storage_directory,
                                         project_yaml,
                                         project_yaml_latest,
                                         args.update)

    # Publish report according to the user's request.
    output = publish_report(report_rst,
                            args,
                            rpc_old_commit,
                            rpc_new_commit)
    print(output)

if __name__ == "__main__":
    run_rpc_differ()
