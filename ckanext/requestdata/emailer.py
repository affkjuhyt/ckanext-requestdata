import logging
import smtplib
import cgi

from socket import error as socket_error
from email import encoders
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from smtplib import SMTPRecipientsRefused
from ckan.common import config


log = logging.getLogger(__name__)

SMTP_SERVER = config.get('smtp.server', '')
SMTP_USER = config.get('smtp.user', '')
SMTP_PASSWORD = config.get('smtp.password', '')
SMTP_FROM = config.get('smtp.mail_from')


def send_email(content, to, subject, file=None):
    '''Sends email
    :param content: The body content for the mail.
    :type string:
    :param to: To whom will be mail sent
    :type string:
    :param subject: The subject of mail.
    :type string:

    :rtype: string
    '''
    from_ = SMTP_FROM

    if isinstance(to, str):
        to = [to]

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = from_
    msg['To'] = ','.join(to)

    html_content = f"""
    <html>
      <head></head>
      <body>
        <span>{content}</span>
      </body>
    </html>
    """

    msg.attach(MIMEText(html_content, 'html', _charset='utf-8'))

    if file and isinstance(file, cgi.FieldStorage):
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(file.file.read())
        encoders.encode_base64(part)

        extension = file.filename.split('.')[-1]

        header_value = 'attachment; filename=attachment.{0}'.format(extension)

        part.add_header('Content-Disposition', header_value)

        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_SERVER, 2525) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(from_, to, msg.as_string())

        return {
            'success': True,
            'message': 'Email message was successfully sent.'
        }
    except SMTPRecipientsRefused:
        return {
            'success': False,
            'error': {
                'fields': {
                    'recepient': 'Invalid email recepient, maintainer not '
                    'found'
                }
            }
        }
    except socket_error:
        log.critical('Could not connect to email server. Have you configured '
                     'the SMTP settings?')
        return {
            'success': False,
            'message': 'An error occured while sending the email. Try again.'
        }
