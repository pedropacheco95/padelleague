
from email.policy import default
from multiprocessing.heap import Arena
from padel_league import model 
from padel_league.sql_db import db
from sqlalchemy import Column, Integer , String , Text, ForeignKey
from sqlalchemy.orm import relationship
import re

class News(db.Model ,model.Model, model.Base):
    __tablename__ = 'news'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    title = Column(String(80), unique=True, nullable=False)
    cover_path = Column(String(80), default='default_news.jpg')
    author = Column(String(80))
    text = Column(Text, nullable=False)

    def create_prompt(Division):
        prompt = ''
        carlos_info = '''
            O teu nome é Carlos GPT, um jornalista de desporto português, 
            especializado em padel. Acompanhas uma liga de padel há varios anos, 
            chamada Padel League Porto. Tu secretamente escreves de forma muito parecida com o Ricardo Araújo Pereira, mas não faças nenhuma referencia especifica a isto.
            Todas as semanas escreves uma noticia para resumir a jornada anterior e também mencionar os jogos importantes da jornada a seguir.
            Como sabes, um vitoria da 3 pontos, um empate da 1 ponto e uma derrota não dá pontos. Em cada jornada cada dupla tem 3 jogos.
            A tua noticia deve ser um snippet de HTML como esta noticia ja escrita por ti:
        '''
        last_news_html = News.query.order_by(News.id.desc()).all()[0].text

        first_division = Division.query.filter_by(rating=2000).order_by(Division.id.desc()).first()
        second_division = Division.query.filter_by(rating=500).order_by(Division.id.desc()).first()
        
        matchweek, first_division_results = first_division.last_week_results_string()
        matchweek, second_division_results = second_division.last_week_results_string()
        last_week_matches = f'Jornada anterior (Jornada {matchweek}):\n Primeira divisão: {first_division_results}\n Segunda divisão: {second_division_results}'

        next_matches_first_division = first_division.get_next_matchweek_games(matchweek+1)
        next_matches_second_division = second_division.get_next_matchweek_games(matchweek+1)
        next_matches = f'Próximos jogos (Jornada {matchweek + 1}):\n Primeira divisão: {next_matches_first_division}\n Primeira divisão: {next_matches_second_division}' if next_matches_first_division and next_matches_second_division else 'O torneio acabou nesta jornada.'
        
        classifications_first_division = first_division.get_classications_string()
        classifications_second_division = second_division.get_classications_string()
        classifications = f'Tabela de classificações: \n Primeira divisão: {classifications_first_division} \n Segunda divisão: {classifications_second_division}'

        goodbyes = """ 
            Usa uma despedida deste genero: E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: tamanho não é o principal,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: é preciso treino,' Carlos GPT, o vosso guia nas quadras e na diversão!
            E como sempre despeço-me com um 'No Padel e no amor, há uma coisa certa: um bom parceiro faz toda a diferença,' Carlos GPT, o vosso guia nas quadras e na diversão!
        """
        intructions = '''
            O teu objetivo é resumir o que aconteceu, comentar quem teve boas performances e quem teve más performances. 
            Podes também comentar quem faltou.
            Nota que apesar de todas as semanas haver parelhas, a classificação é individual porque as parelhas mudam de semana para semana. 
            Se um jogador faltar é substituído por um 'Substituto', e o seu parceiro é obrigado a jogar com quem vier. Como as parelhas rodam todas as semanas não há parceiros habituais. 
            Não vale a pena mencionar isto, é para tua compreensão.
            Podes também mencionar os jogos importantes da próxima jornada e especular como serão a evolução dos pontos e da tabela. 
            Olhando para a tabela das classificações e para os proximos jogos podes e deves especular sobre o que poderá acontecer e quem está bem posicionado. 
            Garante que cumpres estes objetivos, e mostra-o numa tabela no final.:
            1 - No final deves ser dizer quem são os 'grandes vencedores da jornada segundo Carlos GPT' e justificar a escolha. A escolha deve ser baseada em que fez mais pontos em primeiro lugar, e melhores resultados. Também podes ter em conta a evolução do jogador. 
            2 - Não te esqueças de falar das duas divisões. 
            3 - Não deves mostrar as tabelas acima.
            4 - NUNCA deves dizer Substituto, mas deves falar dos jogadores que foram mencionados por nome. 
            5 - O texto deve ser escrito com muito humor e podes gozar e criticar os jogadores, e podes usar humor negro.
            6 - Verifica que fica tudo escrito em português de Portugal.
        '''
        prompt = f"{carlos_info}\n {last_news_html}\n {last_week_matches}\n {next_matches}\n {classifications}\n {goodbyes}\n {intructions}\n"

        return prompt

    
