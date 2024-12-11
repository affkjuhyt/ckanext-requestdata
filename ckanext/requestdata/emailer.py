import logging
import smtplib
import cgi
from socket import error as socket_error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from smtplib import SMTPRecipientsRefused
from ckan.common import config


log = logging.getLogger(__name__)

SMTP_SERVER = config.get('smtp.server', '')
SMTP_USER = config.get('smtp.user', '')
SMTP_PASSWORD = config.get('smtp.password', '')
SMTP_FROM = config.get('smtp.mail_from')

print("SMTP_SERVER: ", SMTP_SERVER)
print("SMTP_USER: ", SMTP_USER)
print("SMTP_PASSWORD: ", SMTP_PASSWORD)
print("SMTP_FROM: ", SMTP_FROM)


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

    msg = MIMEMultipart()

    from_ = SMTP_FROM

    if isinstance(to, str):
        to = [to]

    msg['Subject'] = subject
    msg['From'] = from_
    msg['To'] = ','.join(to)

    content = """\
        <html>
          <head></head>
          <body>
            <span>""" + content + """</span>
          </body>
        </html>
    """

    msg.attach(MIMEText(content, 'html', _charset='utf-8'))

    print("DDDDDDDDDDDDDDDDDDDDDDDDDDDDD")
    if isinstance(file, cgi.FieldStorage):
        print("GGGGGGGGGGGGGGGGGGGGG")
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(file.file.read())
        encoders.encode_base64(part)

        extension = file.filename.split('.')[-1]

        header_value = 'attachment; filename=attachment.{0}'.format(extension)

        part.add_header('Content-Disposition', header_value)

        msg.attach(part)

    try:
        print("SSSSSSSSSSSSSSSSSSSSSSSSSS")
        # s = smtplib.SMTP(SMTP_SERVER)
        # if SMTP_USER:
        #     s.login(SMTP_USER, SMTP_PASSWORD)
        # print("sendingggggggggggggggggg")
        # s.sendmail(from_, to, msg.as_string())
        # s.quit()
        with smtplib.SMTP(SMTP_SERVER, 2525) as server:
            server.starttls()
            print("login")
            server.login(SMTP_USER, SMTP_PASSWORD)
            print("send email")
            server.sendmail(from_, to, msg.as_string())

        print("send successs")
        response_dict = {
            'success': True,
            'message': 'Email message was successfully sent.'
        }
        return response_dict
    except SMTPRecipientsRefused:
        error = {
            'success': False,
            'error': {
                'fields': {
                    'recepient': 'Invalid email recepient, maintainer not '
                    'found'
                }
            }
        }
        print("error: ", error)
        return error
    except socket_error:
        log.critical('Could not connect to email server. Have you configured '
                     'the SMTP settings?')
        error_dict = {
            'success': False,
            'message': 'An error occured while sending the email. Try again.'
        }
        return error_dict
