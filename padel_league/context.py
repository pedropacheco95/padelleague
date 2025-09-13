def inject_sponsors():
    from padel_league.models import Sponsor

    sponsors = Sponsor.query.all()
    return {"sponsors": sponsors}
