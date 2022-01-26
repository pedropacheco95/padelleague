import padel_league as app

run_app = app.create_app()


"""

Se for preciso correr sem 'flask run' talvez seja necessario ter isto:
run_app.run(debug=True) 

(Talvez dentro dum if __name__="__main__")

"""

