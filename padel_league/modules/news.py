from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for , current_app
from werkzeug.security import check_password_hash, generate_password_hash
import unidecode
import os

from padel_league.models import News , Division

bp = Blueprint('news', __name__,url_prefix='/news')

@bp.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        title = request.form['title']
        text = request.form['text']
        author = request.form['author']
        files = request.files.getlist('pictures')
        error = None

        if not author or not text or not title:
            error = 'Tens que adicionar todas as informacoes necessarias.'

        if error is None:
            news = News(author=author, text=text, title=title)
            news.create()

            for index in range(len(files)):
                file = files[index]
                if file.filename != '':
                    image_name = str(title).replace(" ", "").lower()
                    image_name = unidecode.unidecode(image_name)
                    image_name = '{image_name}_{news_id}.jpg'.format(image_name=image_name,news_id=news.id)

                    filename = os.path.join('images',image_name)
                    path = current_app.root_path + url_for('static', filename = filename)
                    file_exists = os.path.exists(path)
                    if not file_exists:
                        img_file = open(path,'wb')
                        img_file.close()
                    file.save(path)

                    news.cover_path = filename
                    news.save()
            
            return redirect(url_for('main.index'))
        flash(error)

    return render_template('news/create.html')

@bp.route('/<news_id>', methods=('GET', 'POST'))
def news(news_id):
    news = News.query.filter_by(id=news_id).first()
    return render_template('news/news.html',news=news)

@bp.route('/delete/<news_id>', methods=('GET', 'POST'))
def delete(news_id):
    news = News.query.filter_by(id=news_id).first()
    news.delete()
    return redirect(url_for('main.index'))

@bp.route('/new_prompt', methods=('GET', 'POST'))
def new_prompt():
    prompt = ''
    carlos_info = '''
        O teu nome é Carlos GPT, um jornalista de desporto português, 
        especializado em padel. Acompanhas uma liga de padel há varios anos, 
        chamada Padel League Porto. 
        Preciso que escrevas uma noticia para resumir a jornada anterior e também mencionar os jogos importantes da jornada a seguir.
        Como sabes, um vitoria da 3 pontos, um empate da 1 ponto e uma derrota não dá pontos. Em cada jornada cada dupla tem 3 jogos.
        A tua noticia deve ser um snippet de HTML como esta noticia ja escrita por ti:
    '''
    last_news_html = News.query.order_by(News.id.desc()).all()[0].text

    first_division = Division.query.filter_by(rating=2000).order_by(Division.id.desc()).first()
    second_division = Division.query.filter_by(rating=500).order_by(Division.id.desc()).first()
    
    matchweek, first_division_results = first_division.last_week_results_string()
    matchweek, second_division_results = second_division.last_week_results_string()
    last_week_matches = f'Jornada anterior (Jornada {matchweek}):\n Primeira divisão: {first_division_results}\n Primeira divisão: {second_division_results}'

    next_matches_first_division = first_division.get_next_matchweek_games(matchweek+1)
    next_matches_second_division = second_division.get_next_matchweek_games(matchweek+1)
    next_matches = f'Próximos jogos (Jornada {matchweek + 1}):\n Primeira divisão: {next_matches_first_division}\n Primeira divisão: {next_matches_second_division}' if next_matches_first_division and next_matches_second_division else 'O torneio acabou nesta jornada.'
    
    classifications_first_division = first_division.get_classications_string()
    classifications_second_division = second_division.get_classications_string()
    classifications = f'Tabela de classificações: \n Primeira divisão: {next_matches_first_division} \n Segunda divisão: {classifications_second_division}'

    goodbyes = """ Usa uma despedida deste genero: E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: tamanho não é o principal,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: a técnica é essencial,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: é preciso treino,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: a resistência faz a diferença,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: um bom parceiro faz toda a diferença,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: nunca subestimem o efeito de um bom slice,' Carlos GPT, o vosso guia nas quadras e na diversão!"""
    intructions = '''
            O teu objetivo é resumir o que aconteceu, 
            comentar quem teve boas performances e quem teve más performances. 
            Podes também comentar quem faltou. 
            Podes também mencionar os jogos importantes da próxima jornada e especular como serão a evolução dos pontos e da tabela. 
            Olhando para a tabela das classificações e para os proximos jogos podes e deves especular sobre o que poderá acontecer e quem está bem posicionado.
            No final deves ser dizer quem são os 'grandes vencedores da jornada segundo Carlos GPT' e justificar a escolha.
            Não deves dizer Substituto, mas deves falar dos jogadores que foram mencionados por nome.
            Não te esqueças de falar das duas divisões.
            Não deves mostrar as tabelas acima.
        '''
    prompt = f"{carlos_info}\n {last_news_html}\n {last_week_matches}\n {next_matches}\n {classifications}\n {goodbyes}\n {intructions}\n"

    print(':::::::::::::::::::::')
    print(':::::::::::::::::::::')
    print(':::::::::::::::::::::')
    print(prompt)
    print(':::::::::::::::::::::')
    print(':::::::::::::::::::::')
    print(':::::::::::::::::::::')

    return prompt