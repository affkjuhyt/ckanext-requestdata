import json
from paste.deploy.converters import asbool
from pylons import config
from email_validator import validate_email
from ckan.lib import base
from ckan import logic, model
from ckan.plugins import toolkit
from ckan.common import c, _, request
from ckan import authz
import ckan.lib.helpers as h
from ckanext.requestdata.emailer import send_email
from ckanext.requestdata import helpers

get_action = logic.get_action
NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
ValidationError = logic.ValidationError

abort = base.abort
BaseController = base.BaseController


def _get_context():
    return {
        'model': model,
        'session': model.Session,
        'user': c.user or c.author,
        'auth_user_obj': c.userobj
    }


def _get_action(action, data_dict):
    return toolkit.get_action(action)(_get_context(), data_dict)


class UserController(BaseController):
    def handle_new_request_action(self, username, request_action):
        '''Handles sending email to the person who created the request, as well
        as updating the state of the request depending on the data sent.

        :param username: The user's name.
        :type username: string

        :param request_action: The current action. Can be either reply or
        reject
        :type request_action: string

        :rtype: json

        '''

        data = dict(toolkit.request.POST)

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

    def handle_open_request_action(self, username, request_action):
        '''Handles updating the state of the request depending on the data
        sent.

        :param username: The user's name.
        :type username: string

        :param request_action: The current action. Can be either shared or
        notshared
        :type request_action: string

        :rtype: json

        '''

        data = dict(toolkit.request.POST)
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
