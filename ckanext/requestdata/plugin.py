import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.requestdata.model import setup as model_setup
from ckanext.requestdata.logic import actions
from ckanext.requestdata.logic import auth
from ckanext.requestdata import helpers
from ckanext.requestdata.logic import validators


@toolkit.blanket.blueprints
class RequestdataPlugin(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IDatasetForm)
    plugins.implements(plugins.IPackageController, inherit=True)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'requestdata')

    def update_config_schema(self, schema):
        ignore_missing = toolkit.get_validator('ignore_missing')

        email_body = {}
        email_body.update({'email_header': [ignore_missing],
                           'email_body': [ignore_missing],
                           'email_footer': [ignore_missing]})

        schema.update(email_body)

        return schema

    # IConfigurable

    def configure(self, config):

        # Setup requestdata model
        model_setup()

    # IActions

    def get_actions(self):
        return {
            'requestdata_request_create': actions.request_create,
            'requestdata_request_show': actions.request_show,
            'requestdata_request_list_for_current_user':
            actions.request_list_for_current_user,
            'requestdata_request_list_for_organization':
            actions.request_list_for_organization,
            'requestdata_request_list_for_sysadmin':
            actions.request_list_for_sysadmin,
            'requestdata_request_patch': actions.request_patch,
            'requestdata_request_update': actions.request_update,
            'requestdata_request_delete': actions.request_delete,
            'requestdata_notification_create': actions.notification_create,
            'requestdata_notification_for_current_user':
            actions.notification_for_current_user,
            'requestdata_notification_change': actions.notification_change,
            'requestdata_increment_request_data_counters':
            actions.increment_request_data_counters,
            'requestdata_request_data_counters_get':
            actions.request_data_counters_get,
            'requestdata_request_data_counters_get_all':
            actions.request_data_counters_get_all,
            'requestdata_request_data_counters_get_by_org':
            actions.request_data_counters_get_by_org
        }

    # IAuthFunctions

    def get_auth_functions(self):
        return {
            'requestdata_request_create': auth.request_create,
            'requestdata_request_show': auth.request_show,
            'requestdata_request_list_for_current_user':
            auth.request_list_for_current_user,
            'requestdata_request_list_for_organization':
            auth.request_list_for_organization,
            'requestdata_request_patch': auth.request_patch,
            'requestdata_request_list_for_sysadmin':
            auth.request_list_for_sysadmin
        }

    # ITemplateHelpers

    def get_helpers(self):
        return {
            'requestdata_time_ago_from_datetime':
                helpers.time_ago_from_datetime,
            'requestdata_get_package_title':
                helpers.get_package_title,
            'requestdata_get_notification':
                helpers.get_notification,
            'requestdata_get_request_counters':
                helpers.get_request_counters,
            'requestdata_convert_id_to_email':
                helpers.convert_id_to_email,
            'requestdata_has_query_param':
                helpers.has_query_param,
            'requestdata_convert_str_to_json': helpers.convert_str_to_json,
            'requestdata_is_hdx_portal':
                helpers.is_hdx_portal,
            'requestdata_is_current_user_a_maintainer':
                helpers.is_current_user_a_maintainer,
            'requestdata_get_orgs_for_user':
                helpers.get_orgs_for_user,
            'requestdata_role_in_org':
                helpers.role_in_org
        }

    # IDatasetForm

    def _modify_package_schema(self, schema):
        not_empty = toolkit.get_validator('not_empty')
        convert_to_extras = toolkit.get_converter('convert_to_extras')
        members_in_org_validator = validators.members_in_org_validator

        schema.update({
            'maintainer': [not_empty, members_in_org_validator,
                           convert_to_extras]
        })

        return schema

    def create_package_schema(self):
        schema = super(RequestdataPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)

        return schema

    def update_package_schema(self):
        schema = super(RequestdataPlugin, self).update_package_schema()
        schema = self._modify_package_schema(schema)

        return schema

    def show_package_schema(self):
        schema = super(RequestdataPlugin, self).show_package_schema()
        not_empty = toolkit.get_validator('not_empty')
        convert_from_extras = toolkit.get_converter('convert_from_extras')

        schema.update({
            'maintainer': [not_empty, convert_from_extras]
        })

        return schema

    def is_fallback(self):
        # Return True to register this plugin as the default handler for
        # package types not handled by any other IDatasetForm plugin.
        return False

    def package_types(self):
        return ['requestdata-metadata-only']

    # IPackageController

    def before_search(self, search_params):
        fq = search_params.get('fq', '')

        if 'dataset_type:dataset' in fq:
            fq = fq.replace('dataset_type:dataset',
                            'dataset_type: (dataset OR '
                            'requestdata-metadata-only)')
            search_params.update({'fq': fq})

        return search_params
