from padel_league import create_app

app = create_app()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

"""

Se for preciso correr sem 'flask run' talvez seja necessario ter isto:
run_app.run(debug=True) 

(Talvez dentro dum if __name__="__main__")

"""

