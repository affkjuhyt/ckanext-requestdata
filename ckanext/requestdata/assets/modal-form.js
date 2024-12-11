'use strict';

/* modal-form
 *
 * This JavaScript module creates a modal and responds to actions
 *
 */

this.ckan.module('modal-form', function(jQuery) {
    return {
        initialize: function() {
            $.proxyAll(this, /_on/);
            this.el.on('click', this._onClick);
        },
        // Track whether the rendered snippet has already been received from CKAN
        _snippetReceived: false,

        _onClick: function(event) {
            var isCurrentUserMaintainer = this.options.is_current_user_a_maintainer;
            var dialogResult = true;

            if (isCurrentUserMaintainer === 'True') {
                dialogResult = window.confirm(
                    'Request own dataset\n\nWARNING: You are a maintainer of the dataset you are requesting. Do you wish to continue making this request?'
                );
            }

            if (dialogResult) {
                var baseUrl = ckan.sandbox().client.endpoint;

                if (!this.options.is_logged_in) {
                    if (this.options.is_hdx === 'True') {
                        showOnboardingWidget('#loginPopup');
                        return;
                    }
                    location.href = baseUrl + this.options.redirect_url;
                    return;
                }

                var payload = {
                    message_content: this.options.message_content,
                    package_name: this.options.post_data.package_name,
                    package_title: this.options.post_data.package_title,
                    maintainers: JSON.stringify(this.options.post_data.maintainers),
                    requested_by: this.options.post_data.requested_by,
                    sender_id: this.options.post_data.sender_id
                };

                if (!this._snippetReceived) {
                    this.sandbox.client.getTemplate(
                        this.options.template_file,
                        payload,
                        this._onReceiveSnippet.bind(this)
                    );
                    this._snippetReceived = true;
                } else if (this.modal) {
                    this.modal.modal('show');
                }

                var successMsg = document.querySelector('#request-success-container');
                if (successMsg) {
                    successMsg.parentElement.removeChild(successMsg);
                }
            }
        },

        _onReceiveSnippet: function(html) {
            if (!html) {
                console.error('Received empty snippet HTML');
                return;
            }
            console.log("html: ", html)
            this.sandbox.body.append(this.createModal(html));
            console.log("FFFFFFFFFFFF: ", this.modal)

            if (typeof jQuery.fn.modal === 'undefined') {
                console.error('Bootstrap modal plugin is not loaded.');
                return;
            } else {
                console.log("Bootstrap work")
            }
            this.modal.modal('show');

            console.log("aAAAAAAA")
            var backdrop = $('.modal-backdrop');
            console.log("backdrop: ", backdrop)
            if (backdrop.length) {
                backdrop.on('click', this._onCancel.bind(this));
            }
        },

        createModal: function(html) {
            if (!this.modal) {
                var element = (this.modal = jQuery(html));
                element.on('click', '.btn-primary', this._onSubmit.bind(this));
                element.on('click', '.btn-cancel', this._onCancel.bind(this));
                element.modal({ show: false });
                this.modalFormError = this.modal.find('.alert-error');
            }
            return this.modal;
        },

        _onSubmit: function(event) {
            event.preventDefault();
            var baseUrl = ckan.sandbox().client.endpoint;
            var url = baseUrl + (this.options.submit_action || '');
            var data = this.options.post_data || {};
            var form = this.modal.find('form');

            if (!form.length) {
                console.error('Form not found inside modal.');
                return;
            }

            var formElements = $(form[0].elements);
            var submit = true;
            var formData = new FormData();

            // Clear previous form errors
            this._clearFormErrors();

            // Add payload data
            for (var item in data) {
                formData.append(item, data[item]);
            }

            // Validate form fields and populate FormData
            $.each(formElements, function(i, element) {
                var value = element.value.trim();

                if (element.required && !value) {
                    this._showInputError(element, 'Missing value');
                    submit = false;
                } else {
                    if (element.type === 'file' && element.files.length > 0) {
                        formData.append(element.name, element.files[0], element.value);
                        formData.append('state', 'archive');
                        formData.append('data_shared', true);
                    } else {
                        formData.append(element.name, value);
                    }
                }
            }.bind(this));

            if (submit) {
                $.ajax({
                    url: url,
                    data: formData,
                    processData: false,
                    contentType: false,
                    type: 'POST'
                })
                    .done(function(data) {
                        if (data.error && data.error.fields) {
                            for (var key in data.error.fields) {
                                this._showFormError(data.error.fields[key]);
                            }
                        } else if (data.success) {
                            this._showSuccessMsg(data.message);
                            if (this.options.disable_action_buttons) {
                                this._disableActionButtons();
                            }
                            if (this.options.refresh_on_success) {
                                location.reload();
                            }
                        }
                    }.bind(this))
                    .fail(function(error) {
                        this._showFormError(error.statusText);
                    }.bind(this));
            }
        },

        _onCancel: function(event) {
            if (event) event.preventDefault();
            this._snippetReceived = false;
            this._clearFormErrors();
            this._resetModalForm();
        },

        _showInputError: function(element, message) {
            var div = document.createElement('div');
            div.className = 'error-block';
            div.textContent = message;

            if (element.parentElement) {
                element.parentElement.appendChild(div);
            } else {
                console.error('Cannot append error message. Parent element is null.');
            }
        },

        _clearFormErrors: function() {
            if (this.modal) {
                var errors = this.modal.find('.error-block');
                $.each(errors, function(i, error) {
                    if (error.parentElement) {
                        error.parentElement.removeChild(error);
                    }
                });
                this.modalFormError.addClass('hide').text('');
            }
        },

        _showFormError: function(message) {
            if (this.modalFormError) {
                this.modalFormError.removeClass('hide').text(message);
            }
        },

        _showSuccessMsg: function(msg) {
            var div = document.createElement('div');
            div.className = 'alert alert-success alert-dismissable fade in';
            div.id = 'request-success-container';
            div.textContent = msg;
            div.style.marginTop = '25px';

            var currentDiv = $('.requested-data-message');
            if (currentDiv.length > 1) {
                currentDiv = this.el.next('.requested-data-message');
            }
            currentDiv.css('display', 'block').append(div);
            this._resetModalForm();
        },

        _resetModalForm: function() {
            if (this.modal) {
                this.modal.modal('hide');
                var form = this.modal.find('form')[0];
                if (form) form.reset();
            }
        },

        _disableActionButtons: function() {
            this.el.attr('disabled', 'disabled');
            this.el.siblings('.btn').attr('disabled', 'disabled');
        }
    };
});
