from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for , current_app
from werkzeug.security import check_password_hash, generate_password_hash
import unidecode
import os

from padel_league.models import News

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
                    image_name = str(title.name).replace(" ", "").lower()
                    image_name = unidecode.unidecode(image_name)
                    image_name = '{image_name}_{news_id}.jpg'.format(image_name=image_name,news_id=news.id)

                    filename = os.path.join('images',image_name)
                    path = current_app.root_path + url_for('static', filename = filename)
                    file_exists = os.path.exists(path)
                    if not file_exists:
                        img_file = open(path,'wb')
                        img_file.close()
                    file.save(path)

                    news.cover_path = path
                    news.save()
            
            return redirect(url_for('main.index'))
        flash(error)

    return render_template('news/create.html')

@bp.route('/<news_id>', methods=('GET', 'POST'))
def news(news_id):
    news = News.query.filter_by(id=news_id).first()
    return render_template('news/news.html',news=news)
