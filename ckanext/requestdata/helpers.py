import json
import timeago
import datetime
import itertools

from operator import itemgetter
from paste.deploy.converters import asbool

from ckan import model, logic
from ckan.common import c, _, request
from ckan.lib import base
from ckan.plugins import toolkit as tk
from ckan.model.user import User

from ckan.common import config

NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
ValidationError = logic.ValidationError


def _get_context():
    return {
        'model': model,
        'session': model.Session,
        'user': c.user or c.author,
        'auth_user_obj': c.userobj
    }


def _get_action(action, data_dict):
    return tk.get_action(action)(_get_context(), data_dict)


def time_ago_from_datetime(date):
    '''Returns a 'time ago' string from an instance of datetime or datetime
    formated string.

    Example: 2 hours ago

    :param date: The parameter which will be formated.
    :type idate: datetime or string

    :rtype: string

    '''

    now = datetime.datetime.now()

    if isinstance(date, datetime.date):
        date = date.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(date, str):
        date = date[:-7]

    return timeago.format(date, now)


def get_package_title(package_id):
    try:
        package = _get_action('package_show', {'id': package_id})
    except NotAuthorized:
        base.abort(403, _('Not authorized to see this package.'))
    except NotFound:
        base.abort(403, _('Package not found.'))

    return package['title']


def get_notification():
    return _get_action('requestdata_notification_for_current_user', {})


def get_request_counters(id):
    '''
        Returns a counters for particular request data

       :param package_id: The id of the package the request belongs to.
       :type package_id: string

     '''

    return _get_action('requestdata_request_data_counters_get', {'package_id': id})


def convert_id_to_email(ids):
    ids = ids.split(',')
    emails = []

    for id in ids:
        user = User.get(id)

        if user:
            emails.append(user.email)
        else:
            emails.append(id)

    return ','.join(emails)


def group_archived_requests_by_dataset(requests):
    sorted_requests = sorted(requests, key=itemgetter('package_id'))
    grouped_requests = []

    for key, group in itertools.groupby(sorted_requests,
                                        key=lambda x: x['package_id']):

        requests = list(group)
        item_shared = requests[0].get('shared')
        item_requests = requests[0].get('requests')

        data = {
            'package_id': key,
            'title': requests[0].get('title'),
            'maintainers': requests[0].get('maintainers'),
            'requests_archived': requests,
            'shared': item_shared,
            'requests': item_requests
        }

        grouped_requests.append(data)

    return grouped_requests


def has_query_param(param):
    params = dict(request.args)

    if param in params:
        return True

    return False


def convert_str_to_json(data):
    try:
        return json.loads(data)
    except Exception:
        return 'string cannot be parsed'


def is_hdx_portal():
    return asbool(config.get('hdx_portal', False))


def is_current_user_a_maintainer(maintainers):
    if c.user:
        current_user = _get_action('user_show', {'id': c.user})
        user_id = current_user.get('id')
        user_name = current_user.get('name')

        if user_id in maintainers or user_name in maintainers:
            return True

    return False


def get_orgs_for_user(user_id):
    try:
        orgs = _get_action('organization_list_for_user', {'id': user_id})

        return orgs
    except Exception:
        return []


def role_in_org(user_id, org_name):
    try:
        org = _get_action('organization_show', {'id': org_name})
    except NotFound:
        return ''

    for user in org.get('users', []):
        if user.get('id') == user_id:
            return user.get('capacity')
