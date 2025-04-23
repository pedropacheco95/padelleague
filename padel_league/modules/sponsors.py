from flask import Blueprint, redirect, request, session

from padel_league.models import Sponsor , SponsorClick , Player , Division

bp = Blueprint('sponsors', __name__,url_prefix='/sponsors')

@bp.route('/sponsor_click/<int:sponsor_id>')
def sponsor_click(sponsor_id):
    sponsor = Sponsor.query.get_or_404(sponsor_id)
    from_page = request.args.get('from_page', None)

    click = SponsorClick(
        sponsor_id=sponsor.id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        referer=request.referrer,
        session_id=session.get('_id'),
        from_page=from_page
    )

    click.create()

    return redirect(sponsor.website)