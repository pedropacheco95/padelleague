from flask_mail import Mail, Message
from ..mail import mail

def send_email(subject, recipients, body=None, html=None):
    msg = Message(
        subject,
        sender='padelleagueporto@gmail.com',
        recipients=recipients
    )
    if body:
        msg.body = body
    if html:
        msg.html = html
    if not (body or html):
        raise ValueError('Either body or html must be provided')
    mail.send(msg)
    return "Sent"
