
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
    
    def news_creation_expressions():
        return "Procura na internet expressões recentes e atuais para descrever padel, ténis ou desporto no geral, para serem usadas numa crónica desportiva."
    
    def news_creation_study_table(Division):
        first_division = Division.query.filter_by(rating=2000).order_by(Division.id.desc()).first()
        second_division = Division.query.filter_by(rating=500).order_by(Division.id.desc()).first()
        matchweek, first_division_results = first_division.last_week_results_string()
        matchweek, second_division_results = second_division.last_week_results_string()
        last_week_matches = f'Jornada anterior (Jornada {matchweek}):\n Primeira divisão: {first_division_results}\n Segunda divisão: {second_division_results}'

        prompt = f"""Faz uma analise dos resultados da ultima jornada da padel 
        league porto, para servir de base para poder escrever uma crónica desportiva:
        \n {last_week_matches}. Nota que cada jogador pode ganhar no máximo mais {(7-matchweek)*9} pontos porque faltam {(7-matchweek)} jornadas. 
        Sê breve. Só é preciso que notes pormenores importantes. 
        A crónica será escrita depois.
        """
        
        return prompt
    
    def news_creation_analyse_week_performance(Division):

        first_division = Division.query.filter_by(rating=2000).order_by(Division.id.desc()).first()
        second_division = Division.query.filter_by(rating=500).order_by(Division.id.desc()).first()
        classifications_first_division = first_division.get_classications_string()
        classifications_second_division = second_division.get_classications_string()
        points_this_week_first_division = first_division.get_last_matchweek_points()
        points_this_week_second_division = second_division.get_last_matchweek_points()

        classifications = f'Tabela de classificações: \n Primeira divisão: {classifications_first_division} \n Segunda divisão: {classifications_second_division}'
        points_this_week = f'Pontos nesta semana: \n Primeira divisão: {points_this_week_first_division} \n Segunda divisão: {points_this_week_second_division}'

        prompt = f"""Faz uma analise dos pontos e da sua evolução na 
        última jornada da padel league porto, 
        para servir de base para poder escrever 
        uma crónica desportiva:
        \n {classifications}. 
        \n {points_this_week}. 
        Sê breve. Só é preciso que notes pormenores importantes. 
        A crónica será escrita depois.
        Só estás a ser um de vários pontos de busca de informação por isso """

        return prompt

    def news_creation_predict_next_week_scores(Division,matchweek):
        first_division = Division.query.filter_by(rating=2000).order_by(Division.id.desc()).first()
        second_division = Division.query.filter_by(rating=500).order_by(Division.id.desc()).first()
        classifications_first_division = first_division.get_classications_string()
        classifications_second_division = second_division.get_classications_string()
        next_matches_first_division = first_division.get_next_matchweek_games(matchweek)
        next_matches_second_division = second_division.get_next_matchweek_games(matchweek)
        classifications = f'Tabela de classificações: \n Primeira divisão: {classifications_first_division} \n Segunda divisão: {classifications_second_division}'
        next_matches = f'Próximos jogos (Jornada {matchweek}):\n Primeira divisão: {next_matches_first_division}\n Primeira divisão: {next_matches_second_division}'

        prompt = f"""
        Analisa os pontos da ultima jornada e tenta adivinhar os resultados da proxima jornada.
        \n {classifications}. 
        \n {next_matches}. 
        Só deves quem achas que vai ganhar cada jogo (ou se achas que vão empatar), e uma muita pequena frase a justificar a escolha. 
        Não escrevas mais nada além disso.
        """
        return prompt

    def get_all_jornalists_inputs(Division):

        first_division = Division.query.filter_by(rating=2000).order_by(Division.id.desc()).first()
        second_division = Division.query.filter_by(rating=500).order_by(Division.id.desc()).first()
        classifications_first_division = first_division.get_classications_string()
        classifications_second_division = second_division.get_classications_string()
        classifications = f'Tabela de classificações: \n Primeira divisão: {classifications_first_division} \n Segunda divisão: {classifications_second_division}'

        last_news_html = News.query.order_by(News.id.desc()).all()[0].text

        description = f"""
        O teu objetivo: 

        Criar uma crónica com muito humor para resumir 
        a jornada da Padel League Porto, uma liga de padel com duas divisões, 
        que vê 16 atletas a competir semanalmente. Deves escrever esta crónica 
        como Carlos GPT, um jornalista português especializado em padel, 
        com uma escrita semelhante à do Ricardo Araujo Pereira (sem nunca o mencionar). 
        Carlos GPT conhece todos os atletas pessoalmente. 
        Escreve usando muito detalhe, algumas palavras caras e pouco comuns, e muita ironia.
        \n {classifications}. 
        Aqui está a última noticia que escreveste:
        \n {last_news_html}. 
        Tens uma equipa de jornalistas a fazer analises para ti, e os inputs deles estão abaixo: 
        """

        context = """
        Contexto:

        - Cada jornada da liga tem 4 duplas criadas por divisão, duplas estas que mudam todas as semanas, até todos os atletas terem jogado uma vez com cada um dos outros.
        - No final cada jogador individualmente recebe pontos correspondendo à sua prestação nessa semana, contribuindo para a sua classificação geral, que é individual.
        - Cada vitoria vale 3 pontos, um empate vale 1 ponto, e uma derrota vale 0 pontos. 
        """
        expressions_guy = """
        Aqui estão algumas expressões populares portuguesas que podem ser utilizadas numa crónica desportiva:

        "À grande e à francesa" - para descrever algo feito com pompa ou em grande escala.
        "Résvés Campo de Ourique" - algo que aconteceu por pouco ou quase não acontece.
        "Como sardinhas em lata" - muitas pessoas num espaço pequeno, como num evento desportivo lotado
        "Como as obras de Santa Engrácia" - algo que demora muito a acontecer
        "Ter as favas contadas" - um resultado inevitável ou certo
        "Não vai ser pêra doce" - uma tarefa ou desafio difícil
        "Ouro sobre azul" - algo que se destaca positivamente
        "Puxar a brasa à nossa sardinha" - agir em benefício próprio, possivelmente de forma estratégica
        "É um pau de dois bicos" - uma situação com opções difíceis ou dilemas
        Estas expressões podem adicionar cor e contexto cultural à sua escrita.
        """
        classifications_guy = """
        Primeira Divisão:

        Equilíbrio Notável: Três dos seis jogos terminaram com diferenças mínimas de pontos, destacando um equilíbrio acentuado entre as equipas. As partidas entre "Cuca ; Dudas VS Talinho ; Substituto" e "Talinho ; Substituto VS Semelhe ; Carlo", bem como "Cuca ; Dudas VS Semelhe ; Carlo" foram particularmente renhidas, evidenciando que uma pequena margem de erro pode decidir o desfecho.
        Substitutos a Brilhar: Uma análise aos jogos indica que as equipas que contaram com substitutos apresentaram desempenhos notáveis, como observado em "Cuca ; Dudas VS Jonny ; Substituto", onde a partida terminou em empate, e "Jonny ; Substituto VS Semelhe ; Carlo", com vitória para a primeira dupla.
        Empates: Nota-se que os empates foram uma constante nesta jornada, algo que pode refletir um nivelamento por cima das equipas.
        
        Segunda Divisão:

        Substituto ; Substituto em Destaque: A equipa "Substituto ; Substituto" merece uma menção especial, participando em três jogos durante esta jornada, com resultados variados, incluindo uma vitória expressiva por 12 - 2 contra "Pipo ; Kikos".
        Desempenhos Oscilantes: "Pipo ; Kikos" teve uma atuação distinta durante esta jornada, sendo derrotados de forma pesada por "Substituto ; Substituto", mas também demonstrando superioridade contra "Pancho ; Freitas".
        Consistência de Malafaya ; Pêras: "Malafaya ; Pêras" mostraram uma sólida performance vencendo os dois jogos disputados. A sua vitória de 10 - 3 contra "Pipo ; Kikos" revelou um domínio a ser observado nas jornadas seguintes.
        Aspectos a Destacar na Notícia:

        A competitividade e o equilíbrio nas partidas da primeira divisão, que podem prever uma reta final de campeonato imprevisível.
        O desempenho louvável dos substitutos, que, apesar de poderem ser jogadores de recurso, mostraram que podem alterar dinâmicas e resultados.
        A consistência e força da equipa "Malafaya ; Pêras", que se mostrou uma candidata sólida com vitórias convincentes na segunda divisão.
        Os altos e baixos de equipas como "Pipo ; Kikos", que podem refletir uma irregularidade a ser explorada por adversários futuros.
        """
        performance_guy = """
        Primeira Divisão:
        Notáveis desta Semana:

        Dudas mantém a liderança, apesar da competição acirrada, ganhando 5 pontos nesta jornada.
        Talinho e Carlo destacaram-se positivamente, ganhando 7 e 6 pontos respectivamente, o que pode indicar uma melhoria no desempenho de ambos.
        Joao perneta e Miguel SG não adicionaram pontos nesta rodada, sendo uma surpresa particularmente para Joao, dado o seu desempenho constante em jornadas anteriores.
        Potenciais Pontos de Discussão:

        A ausência de pontos de alguns dos principais jogadores pode ser explorada na crónica, buscando razões e investigando se há questões de forma, lesões ou outras circunstâncias.
        Segunda Divisão:
        Notáveis desta Semana:

        Malafaya lidera confortavelmente com uma média impressionante de pontos por jornada e adicionou mais 7 à sua conta esta semana.
        Kikos, Pipo e Pêras mostraram um bom desempenho nesta semana, todos ganhando 7 pontos, e pode ser interessante explorar as razões por trás dessa melhoria súbita.
        Bernardo C e Filipe não conseguiram adicionar pontos nesta rodada, o que pode ser um ponto de viragem interessante para a narrativa.
        Potenciais Pontos de Discussão:

        A luta pelo segundo lugar na segunda divisão é digna de nota, com Bernardo C e Kikos empatados em pontos, mas com diferentes desempenhos nas jornadas.
        """
        predictions_guy = """
        Dudas ; Miguel SG VS Jonny ; Joao perneta - Dudas e Miguel apresentam uma média de pontos por jornada elevada.
        Talinho ; Carlo VS Cuca ; Semelhe - Cuca e Semelhe têm melhor desempenho comparando com os adversários.
        Dudas ; Miguel SG VS Talinho ; Carlo - Novamente, Dudas e Miguel mostram uma consistência superior.
        Jonny ; Joao perneta VS Cuca ; Semelhe - Mesmo João tendo uma boa média de pontos por jornada, Cuca e Semelhe apresentam uma dupla mais equilibrada.
        Dudas ; Miguel SG VS Cuca ; Semelhe - Dudas e Miguel mantêm uma superioridade perceptível.
        Jonny ; Joao perneta VS Talinho ; Carlo - Jonny e Joao parecem ter um desempenho mais consistente como dupla.
        Segunda divisão:

        Bernardo C ; Pêras VS Malafaya ; Pancho - Apesar de Malafaya ter uma excelente média, Pêras pode ser o equilíbrio que Bernardo C precisa.
        Freitas ; Kikos VS Filipe ; Pipo - Freitas e Kikos têm um desempenho mais sólido até agora.
        Bernardo C ; Pêras VS Freitas ; Kikos - Poderia ir para qualquer lado, mas vou apostar na dupla Bernardo C e Pêras pela possível estratégia.
        Malafaya ; Pancho VS Filipe ; Pipo - Malafaya e Pancho mostram uma superioridade em termos de pontuação e consistência.
        Bernardo C ; Pêras VS Filipe ; Pipo - A dupla Bernardo C e Pêras parece ser mais forte.
        Malafaya ; Pancho VS Freitas ; Kikos - Este poderia ser um jogo muito próximo, mas a consistência de Kikos pode ser a chave aqui.
        """
        charecteristics_guy = """
        Joao perneta | Muito consistente e calmo (está lesionado).
        Dudas | Muito esforçado, e distraído.
        Miguel SG | Coloca muito bem a bola e consistente.
        Cuca | O mais velho da liga e o mais talentoso.
        Semelhe | Grande jogador, consistente e talentoso.
        Jonny | Muito talento e muitas lesões. Esta lesionado na anca.
        Talinho | Muito boa bandeja e jogo de vidro. Não é rápido.
        Carlo | Uma ótima mão e colocação de bola, mas muito pouco consistente em termos de exibições.
        Malafaya | Muito bom jogador, experiente em padel, esquerdino.
        Bernardo C | Ultra consistente e esforçado.
        Kikos | Esforçado mas nao muito consistente. 
        Pancho | Bom smash mas muito distraído.
        Freitas | Capaz do melhor e do pior.
        Pipo | Cada vez melhor mas cansa-se rápido.
        Filipe | Boa técnica mas irrita-se muito quando começa a falhar.
        Pêras | Boa técnica de padel, entre smash e jogo de vidro, mas irrita-se e desiste do jogo. 
        """
        rules = """
        Garante que cumpres estes objetivos, e mostra-o numa tabela no final.: 
        1 - No final deves ser dizer quem são os 'grandes vencedores da jornada segundo Carlos GPT' , e a escolha deve ser baseada nos resultados. Também podes ter em conta a evolução do jogador. 
        2 - Cria um titulo e subtítulos cativantes, relacionados com as secções do texto a que correspondem
        3 - Não te esqueças de falar das duas divisões.
        4 - Não deves mostrar as tabelas acima. 
        5 - Menciona especificamente pelo menos 2 resultados.
        6 - NUNCA DIGAS Substituto.
        7 - Verifica que fica tudo escrito em português de Portugal. 
        8 - O texto deve ser escrito com muito humor e ironia. Deves gozar e criticar os jogadores com maus resultados, e podes usar humor negro. Deves exaltar os que fizeram melhor resultado do que o esperado (em relação a sua posição na tabela)
        """

        prompt = f"""
        \n {description}
        \n {context}
        \n Opinião sobre expressões:
        \n {expressions_guy}
        \n Opinião sobre classificações:
        \n {classifications_guy}
        \n Opinião sobre performance:
        \n {performance_guy}
        \n Previsões:
        \n {predictions_guy}
        \n Caracteristicas:
        \n {charecteristics_guy}
        \n {rules}
        """

        return prompt