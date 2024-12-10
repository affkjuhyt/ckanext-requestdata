import logging


import ckan.plugins.toolkit as tk
import ckan.model as model

from ckan import logic, authz
from ckan.lib import base
from ckan.common import c, _, request
from ckan.views.group import _get_group_dict, _setup_template_variables
from flask import Blueprint

from collections import Counter
from ckanext.requestdata import helpers
import ckan.lib.helpers as h


log = logging.getLogger(__name__)
bp = Blueprint("requestdata", __name__)

get_action = logic.get_action
NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
ValidationError = logic.ValidationError

abort = base.abort
render = base.render

def _get_context():
    return {
        'model': model,
        'session': model.Session,
        'user': c.user or c.author,
        'auth_user_obj': c.userobj
    }


def _get_action(action, data_dict):
    return tk.get_action(action)(_get_context(), data_dict)


def _setup_template_variables(context, data_dict):
        c.is_sysadmin = authz.is_sysadmin(c.user)
        try:
            user_dict = get_action('user_show')(context, data_dict)
        except NotFound:
            abort(404, _('User not found'))
        except NotAuthorized:
            abort(403, _('Not authorized to see this page'))

        c.user_dict = user_dict
        c.about_formatted = h.render_markdown(user_dict['about'])
 


@bp.route("/<group_type>/requested_data/<id>")
def requested_data(group_type: str, id: str):
    '''Handles creating template for 'Requested Data' page in the
    organization's dashboard.
    :param id: The organization's id.
    :type id: string
    :returns: template
    '''
    try:
        requests = _get_action('requestdata_request_list_for_organization',
                                   {'org_id': id})
        logging.debug("requests: ", requests)
    except NotAuthorized:
        abort(403, _('Not authorized to see this page.'))

    # group_type = self._ensure_controller_matches_group_type(id)
    context = {
        'model': model,
        'session': model.Session,
        'user': c.user
    }
    print("group_type: ", group_type)
    is_organization = True if group_type == "organization" else False
    c.group_dict = _get_group_dict(id, is_organization)
    logging.debug("c.group_dict: ", c.group_dict)
    group_type = c.group_dict['type']
    request_params = request.params.to_dict(flat=False)
    filtered_maintainers = []
    reverse = True
    order = 'last_request_created_at'
    q_organization = ''
    current_order_name = 'Most Recent'

    for item in request_params:
        if item == 'filter_by_maintainers':
            for x in request_params[item]:
                params = x.split('|')
                org = params[0].split(':')[1]
                maintainers = params[1].split(':')[1].split(',')
                maintainers_ids = []

                if maintainers[0] != '*all*':
                    for i in maintainers:
                        try:
                            user = _get_action('user_show', {'id': i})
                            maintainers_ids.append(user['id'])
                        except NotFound:
                            pass

                    data = {
                        'org': org,
                        'maintainers': maintainers_ids
                    }

                    filtered_maintainers.append(data)
        elif item == 'order_by':
            params = request_params[item][0].split('|')
            q_organization = params[1].split(':')[1]
            order = params[0]

            if 'asc' in order:
                reverse = False
                order = 'title'
                current_order_name = 'Alphabetical (A-Z)'
            elif 'desc' in order:
                reverse = True
                order = 'title'
                current_order_name = 'Alphabetical (Z-A)'
            elif 'most_recent' in order:
                reverse = True
                order = 'last_request_created_at'
            elif 'shared' in order:
                current_order_name = 'Sharing Rate'
            elif 'requests' in order:
                current_order_name = 'Requests Rate'

            for x in requests:
                package = \
                    _get_action('package_show', {'id': x['package_id']})
                count = \
                    _get_action('requestdata_request_data_counters_get',
                                {'package_id': x['package_id']})
                x['title'] = package['title']
                x['shared'] = count.shared
                x['requests'] = count.requests
                data_dict = {'id': package['owner_org']}
                current_org = _get_action('organization_show', data_dict)
                x['name'] = current_org['name']

    maintainers = []
    for item in requests:
        package = _get_action('package_show', {'id': item['package_id']})
        package_maintainer_ids = package['maintainer'].split(',')
        item['title'] = package['title']
        package_maintainers = []

        for maint_id in package_maintainer_ids:
            try:
                user = _get_action('user_show', {'id': maint_id})
                username = user['name']
                name = user['fullname']

                if not name:
                    name = username

                payload = {
                            'id': maint_id,
                            'name': name,
                            'username': username,
                            'fullname': name}
                maintainers.append(payload)
                package_maintainers.append(payload)
            except NotFound:
                pass
        item['maintainers'] = package_maintainers

    copy_of_maintainers = maintainers
    maintainers = dict((item['id'], item) for item in maintainers).values()
    organ = _get_action('organization_show', {'id': id})

    # Count how many requests each maintainer has
    for main in maintainers:
        count = Counter(
            item for dct in copy_of_maintainers for item in dct.items())
        main['count'] = count[('id', main['id'])]

    # Sort maintainers by number of requests
    maintainers = sorted(
        maintainers, key=lambda k: k['count'], reverse=True)

    for i, r in enumerate(requests[:]):
        maintainer_found = False

        package = _get_action('package_show', {'id': r['package_id']})
        package_maintainer_ids = package['maintainer'].split(',')
        is_hdx = helpers.is_hdx_portal()

        if is_hdx:
            # Quick fix for hdx portal
            maintainer_ids = []
            for maintainer_name in package_maintainer_ids:
                try:
                    main_ids = \
                        _get_action('user_show', {'id': maintainer_name})
                    maintainer_ids.append(main_ids['id'])
                except NotFound:
                    pass
        data_dict = {'id': package['owner_org']}
        organ = _get_action('organization_show', data_dict)

        # Check if current request is part of a filtered maintainer
        for x in filtered_maintainers:
            if x['org'] == organ['name']:
                for maint in x['maintainers']:
                    if is_hdx:
                        if maint in maintainer_ids:
                            maintainer_found = True
                    else:
                        if maint in package_maintainer_ids:
                            maintainer_found = True

                if not maintainer_found:
                    requests.remove(r)

    requests_new = []
    requests_open = []
    requests_archive = []

    for item in requests:
        if item['state'] == 'new':
            requests_new.append(item)
        elif item['state'] == 'open':
            requests_open.append(item)
        elif item['state'] == 'archive':
            requests_archive.append(item)

    grouped_requests_archive =\
        helpers.group_archived_requests_by_dataset(requests_archive)

    if order == 'last_request_created_at':
        for dataset in grouped_requests_archive:
            created_at =\
                dataset.get('requests_archived')[0].get('created_at')
            data = {
                'last_request_created_at': created_at
            }
            dataset.update(data)

    if organ['name'] == q_organization:
        grouped_requests_archive = sorted(grouped_requests_archive,
                                            key=lambda x: x[order],
                                            reverse=reverse)

    counters =\
        _get_action('requestdata_request_data_counters_get_by_org',
                    {'org_id': organ['id']})

    extra_vars = {
        'requests_new': requests_new,
        'requests_open': requests_open,
        'requests_archive': grouped_requests_archive,
        'maintainers': maintainers,
        'org_name': organ['name'],
        'current_order_name': current_order_name,
        'counters': counters
    }

    _setup_template_variables(context, {'id': id},
                                    group_type=group_type)

    return tk.render(
        'requestdata/organization_requested_data.html',
        extra_vars
    )


@bp.route("/user/my_requested_data/<id>")
def my_requested_data(id: str):
    '''Handles creating template for 'My Requested Data' page in the
    user's dashboard.

    :param id: The user's id.
    :type id: string

    :returns: template

    '''
    try:
        requests = _get_action('requestdata_request_list_for_current_user',
                                {})
    except NotAuthorized:
        abort(403, _('Not authorized to see this page.'))
    
    c.is_myself = id == c.user

    if not c.is_myself:
        abort(403, _('Not authorized to see this page.'))

    order_by = request.query_string
    logging.debug("order_by: ", order_by)
    requests_new = []
    requests_open = []
    requests_archive = []
    reverse = True
    order = 'last_request_created_at'
    current_order_name = 'Most Recent'

    # if order_by != '':
    #     if 'shared' in order_by:
    #         order = 'shared'
    #         current_order_name = 'Sharing Rate'
    #     elif 'requests' in order_by:
    #         order = 'requests'
    #         current_order_name = 'Requests Rate'
    #     elif 'asc' in order_by:
    #         reverse = False
    #         order = 'title'
    #         current_order_name = 'Alphabetical (A-Z)'
    #     elif 'desc' in order_by:
    #         reverse = True
    #         order = 'title'
    #         current_order_name = 'Alphabetical (Z-A)'
    #     elif 'most_recent' in order_by:
    #         reverse = True
    #         order = 'last_request_created_at'

    #     for item in requests:
    #         package =\
    #             _get_action('package_show', {'id': item['package_id']})
    #         count = _get_action('requestdata_request_data_counters_get',
    #                             {'package_id': item['package_id']})
    #         item['title'] = package['title']
    #         item['shared'] = count.shared
    #         item['requests'] = count.requests

    for item in requests:
        try:
            package =\
                _get_action('package_show', {'id': item['package_id']})
            package_maintainers_ids = package['maintainer'].split(',')
            item['title'] = package['title']
        except NotFound as e:
            # package was not found, possibly deleted
            continue
        maintainers = []
        for i in package_maintainers_ids:
            try:
                user = _get_action('user_show', {'id': i})
                payload = {
                    'id': i,
                    'fullname': user['fullname']
                }
                maintainers.append(payload)
            except NotFound:
                pass
        item['maintainers'] = maintainers
        if item['state'] == 'new':
            requests_new.append(item)
        elif item['state'] == 'open':
            requests_open.append(item)
        elif item['state'] == 'archive':
            requests_archive.append(item)

    requests_archive = \
        helpers.group_archived_requests_by_dataset(requests_archive)

    if order == 'last_request_created_at':
        for dataset in requests_archive:
            created_at = \
                dataset.get('requests_archived')[0].get('created_at')
            data = {
                'last_request_created_at': created_at
            }
            dataset.update(data)

    if order:
        requests_archive = \
            sorted(requests_archive,
                    key=lambda x: x[order],
                    reverse=reverse)

    extra_vars = {
        'requests_new': requests_new,
        'requests_open': requests_open,
        'requests_archive': requests_archive,
        'current_order_name': current_order_name
    }

    context = _get_context()
    user_obj = context['auth_user_obj']
    user_id = user_obj.id
    data_dict = {
        'user_id': user_id
    }
    _get_action('requestdata_notification_change', data_dict)

    data_dict = {
        'id': id,
        'include_num_followers': True
    }
    _setup_template_variables(_get_context(), data_dict)

    return tk.render('requestdata/my_requested_data.html', extra_vars)
