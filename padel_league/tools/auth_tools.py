from functools import wraps
from flask import url_for, redirect, request, flash
from flask_login import current_user
from urllib.parse import urlparse, urljoin

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            # If user is not authenticated, redirect to login page with next parameter
            return redirect(url_for('auth.login', next=request.url))
        elif not current_user.is_admin:
            # If user is not an admin, redirect to an appropriate error page or the index page.
            flash('You do not have permission to view this page.')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc