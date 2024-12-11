from ckan.plugins.toolkit import _, get_action
from ckan import logic


def request_create(context, data_dict):
    """
    Handles data request creation.

    :param context: Context dictionary containing user and session details.
    :param data_dict: Dictionary of input data for the request.
    :return: Dictionary indicating success status and optional message.
    """
    return {
        'success': bool(context.get('user')),
        'msg': None if context.get('user') else _('Only registered users can request data.')
    }


def request_show(context, data_dict):
    """
    Handles access verification for request data.

    :param context: Context dictionary containing user and session details.
    :param data_dict: Dictionary of input data for the request.
    :return: Dictionary indicating success status and optional message.
    """
    has_access = _user_has_access_to_request(context, data_dict)
    return {
        'success': has_access,
        'msg': None if has_access else _('You don\'t have access to this request data.')
    }


def request_list_for_current_user(context, data_dict):
    return {'success': True}


def request_list_for_organization(context, data_dict):
    current_user_id = context['auth_user_obj'].id
    org_id = data_dict.get("org_id")

    try:
        organization = get_action('organization_show')(context, {'id': org_id})
    except logic.NotFound:
        raise logic.ValidationError('Organization not found.')

    is_admin = any(
        user['id'] == current_user_id and user['capacity'] == 'admin'
        for user in organization.get('users', [])
    )
    
    return {'success': is_admin}


def request_patch(context, data_dict):
    if _user_has_access_to_request(context, data_dict):
        return {'success': True}
    
    return {
        'success': False,
        'msg': _('You don\'t have access to this request data.')
    }


def request_list_for_sysadmin(context, data_dict):
    model = context['model']
    user = model.User.get(context['user'])

    if user.sysadmin:
        return {'success': True}

    return {'success': False, 'msg': _('You don\'t have access to this request data.')}


def _user_has_access_to_request(context, data_dict):
    current_user_id = context['auth_user_obj'].id

    package = get_action('package_show')(context, {'id': data_dict['package_id']})

    if current_user_id == package['creator_user_id']:
        return True
    
    organization = get_action('organization_show')(context, {'id': package['owner_org']})
    return any(
        user['id'] == current_user_id and user['capacity'] == 'admin'
        for user in organization['users']
    )
