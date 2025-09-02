import padel_league as app

run_app = app.create_app()
run_app.run(host="0.0.0.0", port=80)
