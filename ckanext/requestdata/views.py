import logging
import json
import unicodecsv as csv

import ckan.lib.helpers as h
import ckan.lib.navl.dictization_functions as dict_fns
import ckan.model as model
import ckan.plugins.toolkit as tk

from ckan import logic
from ckan.common import c, _, request, config
from ckan.lib import base
from ckan.views.group import _get_group_dict, _setup_template_variables
from ckan.views.admin import _get_sysadmins

from flask import Blueprint, Response, redirect
from flask import request as rq

from email_validator import validate_email
from collections import Counter
from ckanext.requestdata import helpers
from ckanext.requestdata.emailer import send_email
from paste.deploy.converters import asbool
from io import StringIO


log = logging.getLogger(__name__)
bp = Blueprint("requestdata", __name__)

get_action = logic.get_action
NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
ValidationError = logic.ValidationError
clean_dict = logic.clean_dict
tuplize_dict = logic.tuplize_dict
parse_params = logic.parse_params

abort = base.abort
render = base.render


def _get_context():
    return {
        'model': model,
        'session': model.Session,
        'user': c.user or c.author,
        'auth_user_obj': c.userobj
    }


def _parse_form_data(request):
    return logic.clean_dict(
        dict_fns.unflatten(
            logic.tuplize_dict(
                logic.parse_params(request.form)
            )
        )
    )


def _get_action(action, data_dict):
    return tk.get_action(action)(_get_context(), data_dict)


def _org_admins_for_dataset(dataset_name):
    package = _get_action('package_show', {'id': dataset_name})
    owner_org = package['owner_org']

    org = _get_action('organization_show', {'id': owner_org})

    return [
        {
            'email': model.User.get(user['id']).email,
            'fullname': model.User.get(user['id']).fullname or model.User.get(user['id']).name
        }
        for user in org['users'] if user['capacity'] == 'admin'
    ]


def _get_email_configuration(
    user_name, data_owner, dataset_name, email, message, organization,
    data_maintainers, only_org_admins=False
):
    schema = logic.schema.update_configuration_schema()
    avaiable_terms = ['{name}', '{data_maintainers}', '{dataset}',
                      '{organization}', '{message}', '{email}']
    new_terms = [user_name, data_maintainers, dataset_name, organization,
                 message, email]

    try:
        is_user_sysadmin = \
            _get_action('user_show', {'id': c.user}).get('sysadmin', False)
    except NotFound:
        is_user_sysadmin = False

    email_header = email_body = email_footer = ""
    for key in schema:
        config_value = config.get(key, "")
        if 'email_header' in key:
            email_header = config_value
        elif 'email_body' in key:
            email_body = config_value
        elif 'email_footer' in key:
            email_footer = config_value

    if '{message}' not in email_body and not email_body and not email_footer:
        email_body += message
        return email_body

    for i in range(0, len(avaiable_terms)):
        if avaiable_terms[i] == '{dataset}' and new_terms[i]:
            url = tk.url_for(
                                    controller='package',
                                    action='read',
                                    id=new_terms[i], qualified=True)
            new_terms[i] = '<a href="' + url + '">' + new_terms[i] + '</a>'
        elif avaiable_terms[i] == '{organization}' and is_user_sysadmin:
            new_terms[i] = config.get('ckan.site_title')
        elif avaiable_terms[i] == '{data_maintainers}':
            if len(new_terms[i]) == 1:
                new_terms[i] = new_terms[i][0]
            else:
                maintainers = ''
                for j, term in enumerate(new_terms[i][:]):
                    maintainers += term

                    if j == len(new_terms[i]) - 2:
                        maintainers += ' and '
                    elif j < len(new_terms[i]) - 1:
                        maintainers += ', '

                new_terms[i] = maintainers

        email_header = email_header.replace(avaiable_terms[i], new_terms[i])
        email_body = email_body.replace(avaiable_terms[i], new_terms[i])
        email_footer = email_footer.replace(avaiable_terms[i], new_terms[i])

    if only_org_admins:
        owner_org = _get_action('package_show',
                                {'id': dataset_name}).get('owner_org')
        url = tk.url_for('requestdata_organization_requests', id=owner_org,
                         qualified=True)
        email_body += '<br><br> This dataset\'s maintainer does not exist.\
         Go to your organisation\'s <a href="' + url + '">Requested Data</a>\
          page to see the new request. Please also edit the dataset and assign\
           a new maintainer.'
    else:
        url = \
            tk.url_for('requestdata_my_requests', 
                       id=data_owner, qualified=True)
        email_body += '<br><br><strong> Please accept or decline the request\
         as soon as you can by visiting the \
         <a href="' + url + '">My Requests</a> page.</strong>'

    organizations =\
        _get_action('organization_list_for_user', {'id': data_owner})

    package = _get_action('package_show', {'id': dataset_name})

    if not only_org_admins:
        for org in organizations:
            if org['name'] in organization\
                    and package['owner_org'] == org['id']:
                url = \
                    tk.url_for('requestdata_organization_requests',
                               id=org['name'], qualified=True)
                email_body += '<br><br> Go to <a href="' + url + '">\
                              Requested data</a> page in organization admin.'

    site_url = config.get('ckan.site_url')
    site_title = config.get('ckan.site_title')
    newsletter_url = config.get('ckanext.requestdata.newsletter_url', site_url)
    twitter_url = \
        config.get('ckanext.requestdata.twitter_url', 'https://twitter.com')
    contact_email = config.get('ckanext.requestdata.contact_email', '')

    email_footer += """
        <br/><br/>
        <small>
          <p>
            <a href=" """ + site_url + """ ">""" + site_title + """</a>
          </p>
          <p>
            <a href=" """ + newsletter_url + """ ">\
            Sign up for our newsletter</a> | \
            <a href=" """ + twitter_url + """ ">Follow us on Twitter</a>\
             | <a href="mailto:""" + contact_email + """ ">Contact us</a>
          </p>
        </small>

    """

    return email_header + '<br><br>' + email_body + '<br><br>' + email_footer


@bp.route("/<group_type>/requested_data/<id>")
def requested_data(group_type: str, id: str):
    try:
        requests = _get_action('requestdata_request_list_for_organization',
                               {'org_id': id})
        logging.debug("requests: ", requests)
    except NotAuthorized:
        abort(403, _('Not authorized to see this page.'))

    context = {
        'model': model,
        'session': model.Session,
        'user': c.user
    }
    is_organization = True if group_type == "organization" else False
    c.group_dict = _get_group_dict(id, is_organization)
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
    try:
        requests = _get_action('requestdata_request_list_for_current_user',
                               {})
    except NotAuthorized:
        abort(403, _('Not authorized to see this page.'))
    
    c.is_myself = id == c.user

    if not c.is_myself:
        abort(403, _('Not authorized to see this page.'))

    order_by = request.query_string
    requests_new = []
    requests_open = []
    requests_archive = []
    reverse = True
    order = 'last_request_created_at'
    current_order_name = 'Most Recent'

    if order_by != '':
        if 'shared' in order_by:
            order = 'shared'
            current_order_name = 'Sharing Rate'
        elif 'requests' in order_by:
            order = 'requests'
            current_order_name = 'Requests Rate'
        elif 'asc' in order_by:
            reverse = False
            order = 'title'
            current_order_name = 'Alphabetical (A-Z)'
        elif 'desc' in order_by:
            reverse = True
            order = 'title'
            current_order_name = 'Alphabetical (Z-A)'
        elif 'most_recent' in order_by:
            reverse = True
            order = 'last_request_created_at'

        for item in requests:
            package =\
                _get_action('package_show', {'id': item['package_id']})
            count = _get_action('requestdata_request_data_counters_get',
                                {'package_id': item['package_id']})
            item['title'] = package['title']
            item['shared'] = count.shared
            item['requests'] = count.requests

    for item in requests:
        try:
            package =\
                _get_action('package_show', {'id': item['package_id']})
            package_maintainers_ids = package['maintainer'].split(',')
            item['title'] = package['title']
        except NotFound as e:
            logging.debug("Error: ", e)
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


@bp.route("/ckan-admin/email", methods=["GET", "POST"])
def email():
    data = request.params
    if 'save' in data:
        try:
            data_dict = dict(request.POST)
            del data_dict['save']
            data = _get_action('config_option_update', data_dict)
            h.flash_success(_('Successfully updated.'))
        except logic.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            vars = {'data': data, 'errors': errors,
                    'error_summary': error_summary}
            return base.render('admin/email.html', extra_vars=vars)

    schema = logic.schema.update_configuration_schema()
    data = {}
    for key in schema:
        data[key] = config.get(key)

    vars = {'data': data, 'errors': {}}
    return tk.render('admin/email.html', extra_vars=vars)


@bp.route("/ckan-admin/requests_data")
def requests_data():
    try:
        requests = _get_action('requestdata_request_list_for_sysadmin', {})
    except NotAuthorized:
        abort(403, _('Not authorized to see this page.'))
    organizations = []
    tmp_orgs = []
    filtered_maintainers = []
    filtered_organizations = []
    organizations_for_filters = {}
    reverse = True
    q_organizations = []
    request_params = request.params.to_dict(flat=False)
    order = 'last_request_created_at'

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
        elif item == 'filter_by_organizations':
            filtered_organizations = request_params[item][0].split(',')
        elif item == 'order_by':
            for x in request_params[item]:
                params = x.split('|')
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
                    current_order_name = 'Most Recent'
                elif 'shared' in order:
                    current_order_name = 'Sharing Rate'
                elif 'requests' in order:
                    current_order_name = 'Requests Rate'

                data = {
                    'org': q_organization,
                    'order': order,
                    'reverse': reverse,
                    'current_order_name': current_order_name
                }

                q_organizations.append(data)

            for x in requests:
                package =\
                    _get_action('package_show', {'id': x['package_id']})
                count = \
                    _get_action('requestdata_request_data_counters_get',
                                {'package_id': x['package_id']})
                if count:
                    x['shared'] = count.shared
                    x['requests'] = count.requests
                x['title'] = package['title']
                data_dict = {'id': package['owner_org']}
                current_org = _get_action('organization_show', data_dict)
                x['name'] = current_org['name']

    # Group requests by organization
    for item in requests:
        try:
            package = \
                _get_action('package_show', {'id': item['package_id']})
            package_maintainer_ids = package['maintainer'].split(',')
            data_dict = {'id': package['owner_org']}
            org = _get_action('organization_show', data_dict)
            item['title'] = package['title']
        except NotFound as e:
            logging.debug("Error: ", e)
            continue

        if org['id'] in organizations_for_filters:
            organizations_for_filters[org['id']]['requests'] += 1
        else:
            organizations_for_filters[org['id']] = {
                'name': org['name'],
                'title': org['title'],
                'requests': 1
            }

        if len(filtered_organizations) > 0\
                and org['name'] not in filtered_organizations:
            continue
        maintainers = []
        name = ''
        username = ''
        for id in package_maintainer_ids:
            try:
                user = _get_action('user_show', {'id': id})
                username = user['name']
                name = user['fullname']
                payload = {
                    'id': id,
                    'name': name,
                    'username': username,
                    'fullname': name
                }
                maintainers.append(payload)

                if not name:
                    name = username
            except NotFound:
                pass
        item['maintainers'] = maintainers
        counters = \
            _get_action('requestdata_request_data_counters_get_by_org',
                        {'org_id': org['id']})

        if org['id'] not in tmp_orgs:
            data = {
                'title': org['title'],
                'name': org['name'],
                'id': org['id'],
                'requests_new': [],
                'requests_open': [],
                'requests_archive': [],
                'maintainers': [],
                'counters': counters
            }

            if item['state'] == 'new':
                data['requests_new'].append(item)
            elif item['state'] == 'open':
                data['requests_open'].append(item)
            elif item['state'] == 'archive':
                data['requests_archive'].append(item)

            payload = {'id': id, 'name': name, 'username': username}
            data['maintainers'].append(payload)

            organizations.append(data)
        else:
            current_org = \
                next(item for item in organizations if item['id'] == org['id'])

            payload = {'id': id, 'name': name, 'username': username}
            current_org['maintainers'].append(payload)

            if item['state'] == 'new':
                current_org['requests_new'].append(item)
            elif item['state'] == 'open':
                current_org['requests_open'].append(item)
            elif item['state'] == 'archive':
                current_org['requests_archive'].append(item)

        tmp_orgs.append(org['id'])

    for org in organizations:
        copy_of_maintainers = org['maintainers']
        org['maintainers'] = \
            dict((item['id'], item) for item in org['maintainers']).values()

        # Count how many requests each maintainer has
        for main in org['maintainers']:
            c = Counter(item for dct in copy_of_maintainers
                        for item in dct.items())
            main['count'] = c[('id', main['id'])]

        # Sort maintainers by number of requests
        org['maintainers'] = \
            sorted(org['maintainers'],
                   key=lambda k: k['count'],
                   reverse=True)

        total_organizations = \
            org['requests_new'] + \
            org['requests_open'] +\
            org['requests_archive']

        for i, r in enumerate(total_organizations):
            maintainer_found = False

            package = _get_action('package_show', {'id': r['package_id']})
            package_maintainer_ids = package['maintainer'].split(',')
            is_hdx = helpers.is_hdx_portal()

            if is_hdx:
                # Quick fix for hdx portal
                maintainer_ids = []
                for maintainer_name in package_maintainer_ids:
                    try:
                        main_ids =\
                            _get_action('user_show',
                                        {'id': maintainer_name})
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
                        if r['state'] == 'new':
                            org['requests_new'].remove(r)
                        elif r['state'] == 'open':
                            org['requests_open'].remove(r)
                        elif r['state'] == 'archive':
                            org['requests_archive'].remove(r)

        org['requests_archive'] = \
            helpers.group_archived_requests_by_dataset(
                org['requests_archive'])

        q_org = [x for x in q_organizations if x.get('org') == org['name']]

        if q_org:
            q_org = q_org[0]
            order = q_org.get('order')
            reverse = q_org.get('reverse')
            current_order_name = q_org.get('current_order_name')
        else:
            order = 'last_request_created_at'
            reverse = True
            current_order_name = 'Most Recent'

        org['current_order_name'] = current_order_name

        if order == 'last_request_created_at':
            for dataset in org['requests_archive']:
                created_at = \
                    dataset.get('requests_archived')[0].get('created_at')
                data = {
                    'last_request_created_at': created_at
                }
                dataset.update(data)

        org['requests_archive'] = \
            sorted(org['requests_archive'],
                   key=lambda x: x[order],
                   reverse=reverse)

    organizations_for_filters = sorted(
        organizations_for_filters.items(),
        key=lambda item: item[1]['requests'],
        reverse=True
    )

    total_requests_counters =\
        _get_action('requestdata_request_data_counters_get_all', {})
    extra_vars = {
        'organizations': organizations,
        'organizations_for_filters': organizations_for_filters,
        'total_requests_counters': total_requests_counters
    }

    return tk.render('admin/all_requests_data.html', extra_vars)


@bp.route("/ckan-admin/requests_data/download")
def download_requests_data():
    file_format = request.query_string()
    requests = \
        _get_action('requestdata_request_list_for_sysadmin', {})
    s = StringIO()

    if 'json' in file_format:
        response = Response(
            response=json.dumps(requests, indent=4),
            status=200,
            mimetype='application/json',
        )
        response.headers['Content-Disposition'] = 'attachment;filename="data_requests.json"'
        return response

    if 'csv' in file_format:
        writer = csv.writer(s)
        header = True
        for k in requests:
            if header:
                writer.writerow(k.keys())
                header = False
            writer.writerow(k.values())
        response = Response(
            response=s.getvalue(),
            status=200,
            mimetype='text/csv',
        )
        response.headers['Content-Disposition'] = 'attachment;filename="data_requests.csv"'
        return response

    return Response(
        response='Invalid format. Please specify "json" or "csv".',
        status=400,
        mimetype='text/plain'
    )


@bp.route("/dataset/new", methods=["GET", "POST"])
def create_metadata_package():
    # if helpers.has_query_param('metadata'):
    package_type = 'requestdata-metadata-only'
    form_vars = {
        'errors': {},
        'dataset_type': package_type,
        'action': 'new',
        'error_summary': {},
        'data': {
            'tag_string': '',
            'group_id': None,
            'type': package_type
        },
        'stage': ['active']
    }

    # if tk.request.method == 'POST':
    context = {'model': model, 'session': model.Session,
               'user': c.user, 'auth_user_obj': c.userobj}

    data_dict = clean_dict(dict_fns.unflatten(
        tuplize_dict(parse_params(rq.form))))
    data_dict['type'] = package_type

    try:
        package = get_action('package_create')(context, data_dict)

        url = h.url_for(controller='dataset', action='read',
                        id=package['name'])

        return redirect(url)
    except NotAuthorized:
        abort(403, _('Unauthorized to create a dataset.'))
    except ValidationError as e:
        errors = e.error_dict
        error_summary = e.error_summary

        form_vars = {
            'errors': errors,
            'dataset_type': package_type,
            'action': 'new',
            'error_summary': error_summary,
            'stage': ['active']
        }

        form_vars['data'] = data_dict

        extra_vars = {
            'form_vars': form_vars,
            'form_snippet': 'package/new_package_form.html',
            'dataset_type': package_type
        }

        return tk.render('package/new.html', extra_vars=extra_vars)


@bp.route("/request_data", methods=["POST"])
def send_request():
    '''Send mail to resource owner.

    :param data: Contact form data.
    :type data: object

    :rtype: json
    '''
    context = {'model': model, 'session': model.Session,
               'user': c.user, 'auth_user_obj': c.userobj}
    try:
        if tk.request.method == 'POST':
            data = _parse_form_data(tk.request)
            _get_action('requestdata_request_create', data)
    except NotAuthorized:
        abort(403, _('Unauthorized to update this dataset.'))
    except ValidationError as e:
        error = {
            'success': False,
            'error': {
                'fields': e.error_dict
            }
        }

        return json.dumps(error)

    data_dict = {'id': data['package_id']}
    package = _get_action('package_show', data_dict)
    sender_name = data.get('sender_name', '')
    user_obj = context['auth_user_obj']
    data_dict = {
        'id': user_obj.id,
        'permission': 'read'
    }

    organizations = _get_action('organization_list_for_user', data_dict)

    orgs = []
    for i in organizations:
        orgs.append(i['display_name'])
    org = ','.join(orgs)
    dataset_name = package['name']
    dataset_title = package['title']
    email = user_obj.email
    message = data['message_content']
    creator_user_id = package['creator_user_id']
    data_owner =\
        _get_action('user_show', {'id': creator_user_id}).get('name')
    if _get_sysadmins().count() > 0:
        sysadmin = _get_sysadmins().first().name
        context_sysadmin = {
            'model': model,
            'session': model.Session,
            'user': sysadmin,
            'auth_user_obj': c.userobj
        }
        to = package['maintainer']
        if to is None:
            message = {
                'success': False,
                'error': {
                    'fields': {
                        'email': 'Dataset maintainer email not found.'
                    }
                }
            }

            return json.dumps(message)
        maintainers = to.split(',')
        data_dict = {
            'users': []
        }
        users_email = []
        only_org_admins = False
        data_maintainers = []
        # Get users objects from maintainers list
        for id in maintainers:
            try:
                user =\
                    tk.get_action('user_show')(context_sysadmin, {'id': id})
                data_dict['users'].append(user)
                users_email.append(user['email'])
                data_maintainers.append(user['fullname'] or user['name'])
            except NotFound:
                pass
        mail_subject =\
            config.get('ckan.site_title') + ': New data request "'\
                                            + dataset_title + '"'

        if len(users_email) == 0:
            admins = _org_admins_for_dataset(dataset_name)

            for admin in admins:
                users_email.append(admin.get('email'))
                data_maintainers.append(admin.get('fullname'))
            only_org_admins = True

        content = _get_email_configuration(
            sender_name, data_owner, dataset_name, email,
            message, org, data_maintainers,
            only_org_admins=only_org_admins)

        response_message = \
            send_email(content, users_email, mail_subject)

        # notify package creator that new data request was made
        _get_action('requestdata_notification_create', data_dict)
        data_dict = {
            'package_id': data['package_id'],
            'flag': 'request'
        }

        action_name = 'requestdata_increment_request_data_counters'
        _get_action(action_name, data_dict)

        return json.dumps(response_message)
    else:
        message = {
            'success': True,
            'message': 'Request sent, but email message was not sent.'
        }

        return json.dumps(message)


@bp.route(
    '/user/my_requested_data/<username>/<request_action>',
    methods=['GET', 'POST']
)
def handle_new_request_action(username, request_action):
    data = _parse_form_data(tk.request)

    if request_action == 'reply':
        reply_email = data.get('email')

        try:
            validate_email(reply_email)
        except Exception:
            error = {
                'success': False,
                'error': {
                    'fields': {
                        'email': 'The email you provided is invalid.'
                    }
                }
            }
            return json.dumps(error)

    counters_data_dict = {
        'package_id': data['package_id'],
        'flag': ''
    }
    if 'rejected' in data:
        data['rejected'] = asbool(data['rejected'])
        counters_data_dict['flag'] = 'declined'
    elif 'data_shared' in data:
        counters_data_dict['flag'] = 'shared and replied'
    else:
        counters_data_dict['flag'] = 'replied'

    message_content = data.get('message_content')

    if message_content is None or message_content == '':
        payload = {
            'success': False,
            'error': {
                'message_content': 'Missing value'
            }
        }

        return json.dumps(payload)

    try:
        _get_action('requestdata_request_patch', data)
    except NotAuthorized:
        abort(403, _('Not authorized to use this action.'))
    except ValidationError as e:
        error = {
            'success': False,
            'error': {
                'fields': e.error_dict
            }
        }

        return json.dumps(error)

    to = data['send_to']

    subject = config.get('ckan.site_title') + ': Data request ' +\
        request_action

    file = data.get('file_upload')

    if request_action == 'reply':
        message_content += '<br><br> You can contact the maintainer on '\
            'this email address: ' + reply_email

    response = send_email(message_content, to, subject, file=file)

    if response['success'] is False:
        error = {
            'success': False,
            'error': {
                'fields': {
                    'email': response['message']
                }
            }
        }

        return json.dumps(error)

    success = {
        'success': True,
        'message': 'Message was sent successfully'
    }

    action_name = 'requestdata_increment_request_data_counters'
    _get_action(action_name, counters_data_dict)

    return json.dumps(success)


@bp.route(
    '/user/my_requested_data/<username>/<request_action>',
    methods=['GET', 'POST']
)
def handle_open_request_action(username, request_action):
    data = dict(tk.request.POST)
    if 'data_shared' in data:
        data['data_shared'] = asbool(data['data_shared'])
    data_dict = {
        'package_id': data['package_id'],
        'flag': ''
    }
    if data['data_shared']:
        data_dict['flag'] = 'shared'
    else:
        data_dict['flag'] = 'declined'

    action_name = 'requestdata_increment_request_data_counters'
    _get_action(action_name, data_dict)

    try:
        _get_action('requestdata_request_patch', data)
    except NotAuthorized:
        abort(403, _('Not authorized to use this action.'))
    except ValidationError as e:
        error = {
            'success': False,
            'error': {
                'fields': e.error_dict
            }
        }

        return json.dumps(error)

    success = {
        'success': True,
        'message': 'Request\'s state successfully updated.'
    }

    return json.dumps(success)
