"""
Copyright start
MIT License
Copyright (c) 2026 Fortinet Inc
Copyright end
"""

import zipfile
from zipfile import ZipFile
import requests
import base64
import json
import os
from django.conf import settings
from collections import namedtuple
from github import Github
from github import InputGitTreeElement
import shutil
import hashlib
import tempfile
from .constants import CLONE_ACCEPT_HEADER, CLONE_URL, BINARY_EXTENSIONS
from base64 import b64encode
from datetime import datetime
from connectors.core.connector import get_logger, ConnectorError
from connectors.cyops_utilities.files import download_file_from_cyops, check_file_traversal, save_file_in_env

logger = get_logger('github')

FileMetadata = namedtuple('FileMetadata', ['filename',
                                           'content_length',
                                           'content_type',
                                           'md5',
                                           'sha1',
                                           'sha256'])


class GitHub(object):
    def __init__(self, config):
        self.server_url = config.get('server_url')
        github_type = config.get('github_account')
        if not self.server_url.startswith('https://'):
            self.server_url = 'https://' + self.server_url
        if not self.server_url.endswith('/'):
            self.server_url += '/'
        self.git_username = config.get('username')
        self.password = config.get('password')
        self.verify_ssl = config.get('verify_ssl')
        if github_type == "GitHub Cloud":
            self.clone_url = CLONE_URL
        elif github_type == "GitHub Enterprise":
            self.clone_url = f'{self.server_url}_codeload'
            self.server_url += 'api/v3/'

    def make_request(self, endpoint=None, method='GET', data=None, params=None, owner=None, org=None):
        try:
            if org:
                endpoint = 'repos/' + org + '/' + endpoint
            if owner:
                endpoint = 'repos/' + owner + '/' + endpoint
            url = self.server_url + endpoint
            headers = {'Authorization': 'Bearer ' + self.password, 'Content-Type': 'application/json',
                       'Accept': 'application/vnd.github.v3+json'}
            response = requests.request(method, url, params=params, data=data, headers=headers, verify=self.verify_ssl)
            if response.status_code == 204:
                return
            elif response.ok:
                return response.json()
            elif response.status_code == 404:
                return response.json()
            else:
                logger.error("Response: {0}".format(response.text))
                raise ConnectorError({'status_code': response.status_code, 'message': response.text})
        except requests.exceptions.SSLError:
            raise ConnectorError('SSL certificate validation failed')
        except requests.exceptions.ConnectTimeout:
            raise ConnectorError('The request timed out while trying to connect to the server')
        except requests.exceptions.ReadTimeout:
            raise ConnectorError('The server did not send any data in the allotted amount of time')
        except requests.exceptions.ConnectionError:
            raise ConnectorError('Invalid endpoint or credentials')
        except Exception as err:
            logger.exception(str(err))
            raise ConnectorError(str(err))


def create_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['branch', 'org']}
    if params.get('repo_type') == 'Organization':
        endpoint = 'orgs/{0}/repos'.format(params.get('org'))
    else:
        endpoint = 'user/repos'
    response = github.make_request(endpoint=endpoint, method='POST', data=json.dumps(payload))
    return response


def create_repository_using_template(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['template_owner', 'template_repo']}
    return github.make_request(
        endpoint='repos/{0}/{1}/generate'.format(params.get('template_owner'), params.get('template_repo')),
        method='POST', data=json.dumps(payload))


def get_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    endpoint = '{0}'.format(params.get('repo'))
    response = github.make_request(endpoint=endpoint, org=params.get('org'), owner=params.get('owner'))
    logger.error("Response: {0}".format(response))
    return response


def list_organization_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['type'] = params.get('type', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '_')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k != 'name'}
    return github.make_request(params=query_params, endpoint='orgs/{0}/repos'.format(params.get('org')))


def list_user_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['type'] = params.get('type', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '_')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k != 'username'}
    return github.make_request(params=query_params, endpoint='users/{0}/repos'.format(params.get('username')))


def list_authenticated_user_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params['visibility'] = params.get('visibility', '').lower()
    params['type'] = params.get('type', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '_')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if v is not None and v != '' and v != {} and v != []}
    return github.make_request(params=query_params, endpoint='user/repos')


def update_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    if params.get('other_fields'):
        params.update(params.get('other_fields'))
        del params['other_fields']
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    return github.make_request(method='PATCH', data=json.dumps(payload), endpoint=params.get('repo'),
                               org=params.get('org'), owner=params.get('owner'))


def delete_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    return github.make_request(method='DELETE', endpoint=params.get('repo'), org=params.get('org'),
                               owner=params.get('owner'))


def fork_organization_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    params.pop('repo_type', '')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='repos/{0}/{1}/forks'.format(params.get('owner'), params.get('repo')))


def list_fork_repositories(config, params, *args, **kwargs):
    github = GitHub(config)
    params.pop('repo_type', '')
    params['sort'] = params.get('sort', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/forks'.format(params.get('owner'), params.get('repo')),
                               params=query_params)


def create_update_file_contents(config, params, *args, **kwargs):
    github = GitHub(config)
    content = params.get('content').encode("ascii")
    content = base64.b64encode(content)
    content = content.decode("ascii")
    params.update({'content': content})
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['path', 'owner', 'name', 'org']}
    return github.make_request(method='PUT', data=json.dumps(payload),
                               endpoint='{0}/contents/{1}'.format(params.get('name'),
                                                                  params.get('path')), org=params.get('org'),
                               owner=params.get('owner'))


def add_repository_collaborator(config, params, *args, **kwargs):
    github = GitHub(config)
    params['permission'] = params.get('permission', '').lower()
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'username', 'org']}
    return github.make_request(method='PUT', data=json.dumps(payload), org=params.get('org'), owner=params.get('owner'),
                               endpoint='{0}/collaborators/{1}'.format(params.get('repo'), params.get('username')))


def list_repository_collaborator(config, params, *args, **kwargs):
    github = GitHub(config)
    params['affiliation'] = params.get('affiliation', '').lower()
    params['permission'] = params.get('permission', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo', 'org']}
    return github.make_request(params=query_params, org=params.get('org'), owner=params.get('owner'),
                               endpoint='{0}/collaborators'.format(params.get('repo')))


def get_branch_revision(config, params, *args, **kwargs):
    github = GitHub(config)
    endpoint = 'repos/{0}/{1}/git/refs/heads/{2}'.format(
        params.get('org') if params.get('repo_type') == 'Organization' else params.get('owner'), params.get('repo'),
        params.get('base'))
    return github.make_request(endpoint=endpoint)


def create_branch(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {'ref': 'refs/heads/{0}'.format(params.get('new_branch_name')),
               'sha': params.get('sha') if params.get('checkout_branch') == 'Branch SHA' else
               get_branch_revision(config, params)['object']['sha']}
    return github.make_request(method='POST', data=json.dumps(payload),
                               endpoint='{0}/git/refs'.format(params.get('repo')), org=params.get('org'),
                               owner=params.get('owner'))


def merge_branch(config, params, *args, **kwargs):
    github = GitHub(config)
    params.pop('repo_type', '')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'repo']}
    return github.make_request(endpoint='repos/{0}/{1}/merges'.format(params.get('owner'), params.get('repo')),
                               data=json.dumps(payload), method='POST')


def list_branches(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    if query_params['protected'] is False:
        del query_params['protected']
    return github.make_request(endpoint='{0}/branches'.format(params.get('repo')), params=query_params,
                               org=params.get('org'), owner=params.get('owner'))


def get_commit(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    del query_params['ref']
    return github.make_request(endpoint='{0}/commits/{1}'.format(params.get('repo'), params.get('ref')), params=query_params,
                               org=params.get('org'), owner=params.get('owner'))


def compare_commit(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {
        k: v for k, v in params.items()
        if v not in (None, '', {}, []) and k not in ['owner', 'org', 'repo', 'base', 'head']
    }
    base = params.get('base')
    head = params.get('head')
    repo = params.get('repo')
    endpoint = f'{repo}/compare/{base}...{head}'
    return github.make_request(
        endpoint=endpoint,
        params=query_params,
        org=params.get('org'),
        owner=params.get('owner')
    )


def delete_branch(config, params, *args, **kwargs):
    github = GitHub(config)
    return github.make_request(method='DELETE', org=params.get('org'), owner=params.get('owner'),
                               endpoint='{0}/git/refs/heads/{1}'.format(params.get('repo'), params.get('branch_name')))


def fetch_upstream(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {'branch': params.get('branch')}
    return github.make_request(endpoint='{0}/merge-upstream'.format(params.get('repo')), data=json.dumps(payload),
                               method='POST', org=params.get('org'), owner=params.get('owner'))


def delete_if_exists(path):
    if os.path.exists(path):
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        logger.info(f"Deleted existing path: {path}")


def clone_repository(config, params, *args, **kwargs):
    try:
        github = GitHub(config)
        env = kwargs.get('env', {})

        # Basic repo details
        repo_owner = params.get('org') if params.get('repo_type') == "Organization" else params.get('owner')
        repo_name = params.get('name')
        branch = params.get('branch') or "main"
        safe_branch = branch.replace('/', '-')
        timestamp = datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')

        # Build ZIP download URL
        base_url = github.clone_url.split('//')[-1]
        url = f"https://{config.get('username')}:{config.get('password')}@{base_url}/{repo_owner}/{repo_name}/zip/refs/heads/{branch}"

        # Prepare paths
        archive_name = f"github-{repo_name}-{timestamp}.zip"
        zip_path = os.path.join("/tmp", archive_name)
        unzip_dir = os.path.join("/tmp", f"{repo_name}-{safe_branch}")

        # Clean previous versions
        delete_if_exists(zip_path)
        delete_if_exists(unzip_dir)

        # Download ZIP archive
        headers = CLONE_ACCEPT_HEADER
        response = requests.get(url, headers=headers, verify=config.get('verify_ssl', True))

        if not response.ok:
            logger.error(f"GitHub clone failed: {{status_code: {response.status_code}, error: {response.text}}}")
            raise ConnectorError(f"GitHub clone failed: {{status_code: {response.status_code}, error: {response.text}}}")

        # Write ZIP archive
        with open(zip_path, "wb") as f:
            f.write(response.content)
            logger.info(f"Repository archive saved to: {zip_path}")

        # If just ZIP is needed
        if params.get('clone_zip') is True:
            save_file_in_env(env, zip_path)
            return {"path": zip_path}

        # Else, extract and return folder path
        extract_root = getattr(settings, 'TMP_FILE_ROOT', '/tmp')
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_root)
            logger.info(f"Archive extracted to: {extract_root}")

        # GitHub ZIPs typically unpack to a folder like `repo-branch`
        extracted_root_folder = os.path.join(extract_root, f"{repo_name}-{branch}")

        if os.path.exists(extracted_root_folder):
            shutil.move(extracted_root_folder, unzip_dir)
            logger.info(f"Moved extracted folder to: {unzip_dir}")

        save_file_in_env(env, unzip_dir)
        save_file_in_env(env, zip_path)

        return {"path": unzip_dir}

    except ConnectorError as e:
        raise ConnectorError(e)

    except Exception as e:
        error = str(e)
        password = config.get('password')
        if password and password in error:
            error = error.replace(password, password[:4] + '******************')
        raise ConnectorError(error)
    

def unzip_protected_file(file_iri=None, *args, **kwargs):
    try:
        env = kwargs.get('env', {})
        metadata = download_file_from_cyops(file_iri, None, *args, *args, **kwargs)
        file_name = metadata.get('cyops_file_path', None)
        source_filepath = os.path.join(settings.TMP_FILE_ROOT, file_name)
        target_filepath = os.path.join(settings.TMP_FILE_ROOT, datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f'))
        if os.path.exists(target_filepath):
            shutil.rmtree(target_filepath)
        with ZipFile(source_filepath) as zf:
            zipinfo = zf.infolist()
            for info in zipinfo:
                zf.extract(member=info, path=target_filepath)
        check_file_traversal(target_filepath)
        listOfFiles = list()
        for (dirpath, dirnames, filenames) in os.walk(target_filepath):
            listOfFiles += [os.path.join(dirpath, file) for file in filenames]
        save_file_in_env(env, target_filepath)
        save_file_in_env(env, file_name)
        return {"filenames": listOfFiles}
    except ConnectorError as e:
        raise ConnectorError(e)
    except Exception as e:
        raise ConnectorError(e)


def update_clone_repository(config, params, *args, **kwargs):
    try:
        env = kwargs.get('env', {})
        response = unzip_protected_file(type='File IRI', file_iri=params.get('file_iri'), env=env)
        path = response['filenames'][0].split('/')
        root_src_dir = '/tmp/{0}/{1}/'.format(path[2], path[3])
        root_dst_dir = os.path.abspath(params.get('clone_path'))
        files_from_zip = set()
        root_src_dir = os.path.abspath(root_src_dir)
        for src_dir, dirs, files in os.walk(root_src_dir):
            relative_dir = os.path.relpath(src_dir, root_src_dir)
            if relative_dir == '.':
                dst_dir = root_dst_dir
            else:
                dst_dir = os.path.join(root_dst_dir, relative_dir)
            os.makedirs(dst_dir, exist_ok=True)
            for file_ in files:
                src_file = os.path.join(src_dir, file_)
                dst_file = os.path.join(dst_dir, file_)
                files_from_zip.add(os.path.abspath(dst_file))
                if os.path.exists(dst_file):
                    try:
                        if os.path.samefile(src_file, dst_file):
                            continue
                    except OSError:
                        pass
                fd, temp_file = tempfile.mkstemp(prefix='.__tmp_', dir=dst_dir)
                try:
                    os.close(fd)
                    shutil.copy2(src_file, temp_file)
                    os.replace(temp_file, dst_file)
                finally:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
        for root, dirs, files in os.walk(root_dst_dir):
            for file_ in files:
                file_path = os.path.abspath(os.path.join(root, file_))
                if file_path not in files_from_zip:
                    os.remove(file_path)
        return {'status': 'finish'}
    except Exception as err:
        raise ConnectorError(err)


def push_repository(config, params, *args, **kwargs):
    # Authentication
    token = config.get('password')
    github = GitHub(config)
    g = Github(token, base_url=github.server_url.strip("/"), verify=github.verify_ssl)

    # Get repository object
    if params.get('repo_type') == 'Organization':
        repo = g.get_organization(params.get('org')).get_repo(params.get('name'))
    else:
        repo = g.get_user().get_repo(params.get('name'))

    # Parameters
    root_path = os.path.abspath(params.get('clone_path'))
    branch = params.get('branch', 'main')
    commit_message = params.get('commit_message', 'Update files')
    commit_description = params.get('commit_description', '')
    if commit_description:
        commit_message += '\n' + commit_description

    # Get current commit/tree
    try:
        master_ref = repo.get_git_ref('heads/{}'.format(branch))
    except Exception as e:
        raise ConnectorError("Failed to fetch branch '{}': {}".format(branch, e))
    
    master_sha = master_ref.object.sha
    try:
        base_tree = repo.get_git_tree(master_sha, recursive=True)
    except Exception as e:
        raise ConnectorError("Failed to fetch repository tree: {}".format(e))

    # Get all remote files and their Git blob SHA
    remote_files = {}

    for element in base_tree.tree:
        if element.type == 'blob':
            remote_files[element.path] = element.sha

    remote_paths = set(remote_files.keys())

    # Git blob SHA calculation
    def calculate_git_blob_sha(data):
        header = b'blob ' + str(len(data)).encode('ascii') + b'\0'
        return hashlib.sha1(header + data).hexdigest()
    # Collect local files
    element_list = []
    local_paths = set()
    files_added_or_updated = []

    try:
        for root, dirs, files in os.walk(root_path):
            # Do not process .git directories
            dirs[:] = [
                d for d in dirs
                if d != '.git'
            ]
            for file_name in files:

                # Skip unwanted files
                if file_name == '.DS_Store':
                    continue
                full_path = os.path.join(root, file_name)
                # Relative path used by Git
                rel_path = os.path.relpath(full_path, root_path)
                # Git uses forward slashes
                rel_path = rel_path.replace(os.sep, '/')
                local_paths.add(rel_path)

                remote_sha = remote_files.get(rel_path)

                # Binary files
                if file_name.lower().endswith(BINARY_EXTENSIONS):
                    with open(full_path, 'rb') as input_file:
                        binary_data = input_file.read()
                    local_sha = calculate_git_blob_sha(binary_data)

                    # Skip unchanged file
                    if remote_sha == local_sha:
                        continue

                    # Create new Git blob
                    encoded_data = base64.b64encode(binary_data).decode('ascii')
                    try:
                        blob = repo.create_git_blob(encoded_data, 'base64')
                    except Exception as e:
                        raise ConnectorError("Failed to create Git blob for '{}': {}".format(rel_path, e))

                    element = InputGitTreeElement(path=rel_path, mode='100644', type='blob', sha=blob.sha)

                # Text files
                else:
                    with open(full_path, 'r', encoding='utf-8') as input_file:
                        data = input_file.read()
                    text_bytes = data.encode('utf-8')
                    local_sha = calculate_git_blob_sha(text_bytes)

                    # Skip unchanged file
                    if remote_sha == local_sha:
                        continue

                    element = InputGitTreeElement(path=rel_path, mode='100644', type='blob', content=data)
                element_list.append(element)
                files_added_or_updated.append(rel_path)
    except Exception as err:
        raise ConnectorError(
            "Error reading files: {}".format(err)
        )

    # Detect deleted files
    files_to_delete = remote_paths - local_paths
    for file_path in files_to_delete:
        element = InputGitTreeElement(path=file_path, mode='100644', type='blob', sha=None)
        element_list.append(element)

    # No changes safeguard
    if not element_list:
        return {"status": "no changes to commit"}

    # Create tree
    try:
        new_tree = repo.create_git_tree(element_list, base_tree)
    except Exception as e:
        raise ConnectorError("Failed to create Git tree: {}".format(e))

    # Create commit
    try:
        parent = repo.get_git_commit(master_sha)
        commit = repo.create_git_commit(commit_message, new_tree, [parent])
    except Exception as e:
        raise ConnectorError("Failed to create Git commit: {}".format(e))

    # Update branch
    try:
        master_ref.edit(commit.sha)
    except Exception as e:
        raise ConnectorError("Failed to update branch '{}': {}".format(branch, e))
    return {
        "status": "finished",
        "commit_sha": commit.sha,
        "files_added_or_updated": files_added_or_updated,
        "files_deleted": list(files_to_delete)
    }


def create_pull_request(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    return github.make_request(method='POST', data=json.dumps(payload), endpoint='{0}/pulls'.format(params.get('repo')),
                               org=params.get('org'), owner=params.get('owner'))


def list_pull_request(config, params, *args, **kwargs):
    github = GitHub(config)
    params['state'] = params.get('state', '').lower()
    params['sort'] = (params.get('sort', '').lower()).replace(' ', '-')
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo',
                                                                                    'pull_number']}
    if params.get('pull_number'):
        endpoint = '{0}/pulls/{1}'.format(params.get('repo'), params.get('pull_number'))
    else:
        endpoint = '{0}/pulls'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'), owner=params.get('owner'))


def add_reviewers(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'pull_number']}
    body_params = {}
    for k, v in payload.items():
        if v:
            if isinstance(v, str):
                body_params.update({k: list(map(lambda x: x.strip(' '), v.split(",")))})
            elif isinstance(v, list):
                body_params.update({k: list(map(str, v))})
    endpoint = '{0}/pulls/{1}/requested_reviewers'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(method='POST', data=json.dumps(body_params), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_review_comments(config, params, *args, **kwargs):
    github = GitHub(config)
    params['sort'] = params.get('sort', '').lower()
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo',
                                                                                    'pull_number']}
    endpoint = '{0}/pulls/{1}/comments'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_pr_reviews(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo',
                                                                                    'pull_number']}
    endpoint = '{0}/pulls/{1}/reviews'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def add_pr_review(config, params, *args, **kwargs):
    github = GitHub(config)
    params['event'] = (params.get('event', '').upper()).replace(' ', '_')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'pull_number']}
    endpoint = '{0}/pulls/{1}/reviews'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def merge_pull_request(config, params, *args, **kwargs):
    github = GitHub(config)
    params['merge_method'] = params.get('merge_method', '').lower()
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'pull_number']}
    endpoint = '{0}/pulls/{1}/merge'.format(params.get('repo'), params.get('pull_number'))
    return github.make_request(method='PUT', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def create_issue(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/issues'.format(params.get('repo'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_repository_issue(config, params, *args, **kwargs):
    github = GitHub(config)
    params['state'] = params.get('state', '').lower()
    params['sort'] = params.get('sort', '').lower()
    params['direction'] = params.get('direction', '').lower()
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/issues'.format(params.get('repo'))
    response = github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                                   owner=params.get('owner'))
    for e in range(len(response) - 1, -1, -1):
        if response[e].get('pull_request') is not None:
            response.pop(e)
    return response


def update_issue(config, params, *args, **kwargs):
    github = GitHub(config)
    params['state'] = params.get('state', '').lower()
    params['state_reason'] = (params.get('state_reason', '').lower()).replace(' ', '_')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo', 'issue_number']}
    endpoint = '{0}/issues/{1}'.format(params.get('repo'), params.get('issue_number'))
    return github.make_request(method='PATCH', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def create_issue_comment(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {"body": params.get('body')}
    endpoint = '{0}/issues/{1}/comments'.format(params.get('repo'), params.get('issue_number'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def create_release(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/releases'.format(params.get('repo'))
    return github.make_request(method='POST', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_releases(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/releases'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def list_stargazers(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/stargazers'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def star_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    endpoint = 'user/starred/{0}/{1}'.format(
        params.get('org') if params.get('repo_type') == 'Organization' else params.get('owner'), params.get('repo'))
    return github.make_request(method='PUT', endpoint=endpoint)


def list_watchers(config, params, *args, **kwargs):
    github = GitHub(config)
    query_params = {k: v for k, v in params.items() if
                    v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/subscribers'.format(params.get('repo'))
    return github.make_request(params=query_params, endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def set_repo_subscription(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != [] and k not in ['owner', 'org', 'repo']}
    endpoint = '{0}/subscription'.format(params.get('repo'))
    return github.make_request(method='PUT', data=json.dumps(payload), endpoint=endpoint, org=params.get('org'),
                               owner=params.get('owner'))


def _check_health(config):
    try:
        github = GitHub(config)
        response = github.make_request(endpoint='user')
        if response:
            if response.get('login') == github.git_username:
                return True
            raise ConnectorError("Invalid Username or Personal Access Token provided")
        else:
            raise ConnectorError("{} error: {}".format(response.status_code, response.reason))
    except Exception as err:
        raise ConnectorError(err)


def get_web_url(config, params, *args, **kwargs):
    github = GitHub(config)
    response = github.make_request(endpoint='user')
    username = response.get('login')
    web_url = response.get('html_url')
    result = {
        "server_url": web_url.split(username)[0]
    }
    return result


def get_file_from_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {'ref': params.get('branch') if params.get('branch') else 'main'}
    endpoint = '{0}/contents/{1}'.format(params.get('name'), params.get('path'))
    response = github.make_request(endpoint=endpoint, org=params.get('org'), owner=params.get('owner'), params=payload)
    if params.get('decode_content') and response.get('content'):
        try:
            decoded_bytes = base64.b64decode(response.get('content'))
            response['content'] = decoded_bytes.decode('utf-8')
        except Exception as err:
            logger.error(err)
    return response


def delete_file_from_repository(config, params, *args, **kwargs):
    github = GitHub(config)
    payload = {
        "message": params.get('message'),
        "sha": params.get('sha'),
        "branch": params.get('branch') if params.get('branch') else 'main'
    }
    endpoint = '{0}/contents/{1}'.format(params.get('name'), params.get('path'))
    response = github.make_request(method='DELETE', endpoint=endpoint, org=params.get('org'), owner=params.get('owner'),
                                   data=json.dumps(payload))
    return response


def search_code(config, params, *args, **kwargs):
    github = GitHub(config)
    params['q'] = params.pop('query', '')
    payload = {k: v for k, v in params.items() if
               v is not None and v != '' and v != {} and v != []}
    endpoint = f"search/code"
    return github.make_request(method='GET', endpoint=endpoint, params=payload)


operations = {
    'create_repository': create_repository,
    'create_repository_using_template': create_repository_using_template,
    'get_repository': get_repository,
    'list_organization_repositories': list_organization_repositories,
    'list_user_repositories': list_user_repositories,
    'list_authenticated_user_repositories': list_authenticated_user_repositories,
    'update_repository': update_repository,
    'delete_repository': delete_repository,
    'fork_organization_repository': fork_organization_repository,
    'list_fork_repositories': list_fork_repositories,
    'create_update_file_contents': create_update_file_contents,
    'add_repository_collaborator': add_repository_collaborator,
    'list_repository_collaborator': list_repository_collaborator,
    'get_branch_revision': get_branch_revision,
    'create_branch': create_branch,
    'merge_branch': merge_branch,
    'delete_branch': delete_branch,
    'create_issue': create_issue,
    'update_issue': update_issue,
    'create_issue_comment': create_issue_comment,
    'list_repository_issue': list_repository_issue,
    'list_branches': list_branches,
    'get_commit': get_commit,
    'compare_commit': compare_commit,
    'fetch_upstream': fetch_upstream,
    'clone_repository': clone_repository,
    'update_clone_repository': update_clone_repository,
    'push_repository': push_repository,
    'create_pull_request': create_pull_request,
    'list_pull_request': list_pull_request,
    'add_reviewers': add_reviewers,
    'list_review_comments': list_review_comments,
    'list_pr_reviews': list_pr_reviews,
    'add_pr_review': add_pr_review,
    'merge_pull_request': merge_pull_request,
    'list_releases': list_releases,
    'create_release': create_release,
    'list_stargazers': list_stargazers,
    'star_repository': star_repository,
    'list_watchers': list_watchers,
    'set_repo_subscription': set_repo_subscription,
    'get_web_url': get_web_url,
    'get_file_from_repository': get_file_from_repository,
    'delete_file_from_repository': delete_file_from_repository,
    'search_code': search_code
}
