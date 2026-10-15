import re
from pandas.errors import DatabaseError
import json
import copy
from .llm_handler import LLMConversation, LLMClient


class Agent:
    def __init_subclass__(cls):
        super().__init_subclass__()
        if not hasattr(cls, "name") or not hasattr(cls, "description"):
            raise TypeError(
                f"Class '{cls.__name__}' must define 'name' and 'description'."
            )

    def run(self, **kwargs):
        raise NotImplementedError


class DataAgent(Agent):

    name = "DataAgent"
    description = """
    Retrieves structured data from the SQL database.
    Takes a fully-formed question about padel, the league,
    divisions, matches, schedules, rankings, or players.
    """

    system_prompt = """
    You're a Postgres SQL expert.
    """

    def __init__(self, api_key, sql_client):
        self.llm_client = LLMClient(api_key=api_key, model="gpt-5.1")
        self.sql_client = sql_client

        self.schema = """
        ## Table leagues
        leagues (id BIGINT PRIMARY KEY, name TEXT)

        ## Table seasons -- a season runs September to July, e.g. '2026/27'
        seasons (id INTEGER PRIMARY KEY, league_id BIGINT REFERENCES leagues(id), name TEXT,
                 starts_on DATE, ends_on DATE)

        ## Table competitions -- one tournament: a Clássica edition ("22ª Edição"), a Shuffle, a Teams edition
        competitions (
        id BIGINT PRIMARY KEY,
        season_id INTEGER REFERENCES seasons(id),
        name TEXT,                -- e.g. '22ª Edição'; Shuffle/Teams may use title instead
        title TEXT,
        format TEXT,              -- 'classica' | 'shuffle' | 'teams' | 'super_cup'
        status TEXT,              -- 'planned' | 'running' | 'ended'
        starts_on DATE,
        ends_on DATE
        )

        ## Table stages -- a period in which the groups stay fixed (Clássica: one stage; Shuffle: one per week)
        stages (id INTEGER PRIMARY KEY, competition_id BIGINT REFERENCES competitions(id), number INTEGER,
                name TEXT, status TEXT)

        ## Table competition_groups -- a DIVISION (Clássica "1ª Divisão", or a Shuffle/Teams division)
        competition_groups (
        id BIGINT PRIMARY KEY,
        stage_id INTEGER REFERENCES stages(id),
        tier INTEGER,             -- 1 = top division of its stage
        name TEXT,                -- e.g. 'Masters de Outono - 1ª Divisão'
        rating BIGINT,            -- Clássica: 2000, 1000, 500, 250, 125, 63 (1ª..6ª)
        multiplier INTEGER,       -- Shuffle division weight
        starts_at TIMESTAMP,
        end_date TIMESTAMP,
        has_ended BOOLEAN,
        open_division BOOLEAN
        )

        ## Table rounds -- a JORNADA (matchweek) of a stage; shared by all divisions of that stage
        rounds (id INTEGER PRIMARY KEY, stage_id INTEGER REFERENCES stages(id), number INTEGER, date DATE)

        ## Table players
        players (
        id BIGINT PRIMARY KEY,
        name TEXT,
        full_name TEXT,
        birthday TIMESTAMP,
        ranking_points BIGINT,    -- current GLOBAL league ranking
        ranking_position BIGINT,  -- 1 = best; 0/NULL = unranked
        height DOUBLE PRECISION,
        prefered_hand TEXT,
        prefered_position TEXT
        )

        ## Table entries -- a player's registration in one competition
        entries (id INTEGER PRIMARY KEY, competition_id BIGINT REFERENCES competitions(id),
                 player_id BIGINT REFERENCES players(id),
                 status TEXT,     -- 'active' | 'withdrawn' | 'replaced'
                 final_place INTEGER)

        ## Table group_members -- which entries play in which division
        group_members (id BIGINT PRIMARY KEY, group_id BIGINT REFERENCES competition_groups(id),
                       entry_id INTEGER REFERENCES entries(id))

        ## Table matches -- a JOGO
        matches (
        id BIGINT PRIMARY KEY,
        group_id BIGINT REFERENCES competition_groups(id),
        round_id INTEGER REFERENCES rounds(id),
        scheduled_at TIMESTAMP,
        court TEXT,               -- e.g. 'Campo 1'
        status TEXT               -- 'scheduled' | 'played'
        )

        ## Table match_sets -- the score. Clássica/Shuffle: one row, set_no = 1. Teams: up to 3 sets.
        match_sets (match_id BIGINT REFERENCES matches(id), set_no SMALLINT,
                    home_games INTEGER, away_games INTEGER)

        ## Table match_participants -- who played each match
        match_participants (
        id BIGINT PRIMARY KEY,
        match_id BIGINT REFERENCES matches(id),
        side TEXT,                -- 'home' | 'away'
        slot SMALLINT,            -- 1 | 2
        role TEXT,                -- 'member' (player of the division) | 'substitute'
        entry_id INTEGER REFERENCES entries(id),   -- NULL for substitutes
        player_id BIGINT REFERENCES players(id)
        )

        ## Table absences -- a FALTA: an entry missing a jornada
        absences (id INTEGER PRIMARY KEY, entry_id INTEGER REFERENCES entries(id),
                  round_id INTEGER REFERENCES rounds(id), kind TEXT)

        ## Table standing_snapshots -- final standings of a FINISHED division, exactly as published
        standing_snapshots (
        id BIGINT PRIMARY KEY,
        entry_id INTEGER REFERENCES entries(id),
        group_member_id BIGINT REFERENCES group_members(id),
        place INTEGER, points DOUBLE PRECISION, appearances BIGINT, percentage_of_appearances DOUBLE PRECISION,
        wins BIGINT, draws BIGINT, losses BIGINT, games_won BIGINT, games_lost BIGINT
        )

        ## Table awards -- ranking points a player earned from one division
        awards (id INTEGER PRIMARY KEY, entry_id INTEGER REFERENCES entries(id),
                player_id BIGINT REFERENCES players(id), group_id BIGINT REFERENCES competition_groups(id),
                place INTEGER, rating BIGINT, place_points DOUBLE PRECISION, bonus_points DOUBLE PRECISION,
                wins INTEGER, draws INTEGER)
        """

    def ask_llm_client(self, prompt):
        return self.llm_client.generate_response(
            prompt=prompt,
            reasoning_effort="none",
            temperature=0,
            verbosity="low",
            initial_instruction=self.system_prompt,
        )

    def extract_sql_block(self, text: str) -> str:
        """
        Extracts the SQL inside ```sql ... ``` from an LLM response.
        Raises a clean exception if no SQL is found.
        """
        match = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL)
        if not match:
            raise ValueError("No SQL code block found in LLM output.")
        return match.group(1).strip()

    def repair_sql(self, question, faulty_sql, db_error):
        """
        Sends the schema, faulty SQL and error to the LLM
        and asks for a corrected SQL-only output.
        """
        repair_prompt = f"""
            You are an expert PostgreSQL fixer.

            You will receive:
            - The database schema
            - A natural-language question
            - The faulty SQL the previous LLM generated
            - The exact DatabaseError message

            Your task:
            - Analyze the faulty SQL
            - Identify the mistake
            - Output a corrected SQL query
            - Follow *all* the semantic rules in the schema description

            Return ONLY a ```sql ... ``` block.

            ---
            # Schema
            {self.schema}

            ---
            # Question
            {question}

            ---
            # Faulty SQL
            ```sql
            {faulty_sql}
            ```

            Database Error
            {db_error}

            Output corrected SQL (only SQL in codeblock)
        """

        llm_answer = self.llm_client.generate_response(
            prompt=repair_prompt,
            reasoning_effort="medium",
            verbosity="low",
            temperature=0,
        )
        return self.extract_sql_block(llm_answer)

    def prompt(self, user_question):
        return f"""
        You are an expert in SQL that writes accurate, safe PostgreSQL SQL queries for a database about a friendly padel league.
        Your job is to read a natural-language question and output only SQL, respecting the schema and all semantic rules.
        You are an agent that is tasked to retrieve enough information so that another agent can answer the final user.

        ---

        # Database Schema

        {self.schema}

        ---

        # Crucial Semantic Rules (INSIGHTS)

        1. A "divisão" is a row of competition_groups; an "edição" is a competition with format = 'classica'.
           Path: competitions -> stages (competition_id) -> competition_groups (stage_id).
        2. Current division = has_ended = FALSE. Current edition = the classica competition whose
           divisions have has_ended = FALSE; if none is running, the latest one (ORDER BY starts_on DESC).
        3. Closed edition = all its divisions have has_ended = TRUE (competitions.status = 'ended').
        4. When asked about a "Divisão", default to the classica division with that rating in the current edition.
        5. "Última edição" usually means the last closed classica edition.
        6. Classica divisions are identified by rating, not name:
           2000 → 1ª, 1000 → 2ª, 500 → 3ª, 250 → 4ª, 125 → 5ª, 63 → 6ª.
        7. For place/points/faltas questions about a division → current edition.
        8. For historical counts → all editions (format = 'classica' unless Shuffle/Teams is asked).
        9. A match is played when matches.status = 'played'. Its score is the match_sets row with set_no = 1
           (home_games, away_games). A side WINS when its games are greater; equal games is a draw.
        10. A player's own games in a match: home_games if side = 'home', else away_games.
        11. Jornada (matchweek) N = rounds.number = N, joined via matches.round_id.
        12. match_participants shows who played each match; a missing player (falta) is in absences, and a
            substitute appears with role = 'substitute' and entry_id NULL.
        13. Players of a division: group_members -> entries -> players (entries.player_id).
        14. Final standings of a FINISHED division are in standing_snapshots (join group_members on
            group_member_id); use place from there. For a division still running, compute standings from
            its played matches: 3 points per win, 1 per draw, ordered by points DESC, appearances DESC,
            (games_won - games_lost) DESC.
        15. Improvements only between closed editions. melhoria = place_prev - place_curr.
        16. Include edition names and division ratings when comparing improvements.
        17. 'Parelha' are the 2 players on the same side of a match in one jornada (same match_id, same side).
            'Parelha de X' is the player that played on X's side in a certain jornada.
        18. Being promoted means being in the top 2 places of a division at the end; being relegated means the
            bottom 2 places.
        19. To understand how many points a player would need to be champion, compare the points of the
            1st place and the points of that player.
        20. If a question implies a comparison, return enough information for the final agent to craft a
            complete answer.
        21. Always use explicit joins via IDs. Do NOT compare TEXT with BIGINT.
        22. Use correct PostgreSQL types consistently; avoid non-existent columns; follow strict GROUP BY rules.
        23. The GLOBAL league ranking ("ranking geral", "ranking da liga", "melhor jogador da liga",
            "quem está no topo do ranking") lives in players.ranking_points and players.ranking_position
            (position 1 = best). It is NOT division points and needs no join with divisions.
            Unranked players have ranking_position = 0 or NULL and ranking_points = 0: ALWAYS exclude
            them (WHERE ranking_position > 0). Order by ranking_points DESC, ranking_position ASC.
        24. Ranking points earned in one division are in awards (place_points + bonus_points).


        ---

        # Interpreting ambiguous questions
        - "Divisão X" → current edition's division.
        - "Última edição" → last closed edition.
        - Historical questions → all editions.
        - "Quantas vezes jogou a 1ª divisão?" → count classica divisions with rating = 2000 the player was a member of.
        ---

        # Final Instructions
        - Output pure SQL only.
        - Always apply insights.
        - Prefer CTEs for complex logic.

        Example:

        Input question:

        "Quantas vitórias tem cada jogador da Divisão 3?"

        Output:

        ```sql
        WITH div3 AS (
            SELECT g.id
            FROM competition_groups g
            JOIN stages st ON st.id = g.stage_id
            JOIN competitions c ON c.id = st.competition_id
            WHERE c.format = 'classica'
            AND g.rating = 500
            ORDER BY g.has_ended ASC, c.starts_on DESC NULLS LAST, g.id DESC
            LIMIT 1
        ),
        vitorias AS (
            SELECT
                mp.player_id,
                COUNT(*) AS vitorias
            FROM matches m
            JOIN match_sets s ON s.match_id = m.id AND s.set_no = 1
            JOIN match_participants mp ON mp.match_id = m.id
            WHERE m.group_id = (SELECT id FROM div3)
            AND m.status = 'played'
            AND (
                    (mp.side = 'home' AND s.home_games > s.away_games)
                OR  (mp.side = 'away' AND s.away_games > s.home_games)
            )
            GROUP BY mp.player_id
        )
        SELECT
            p.name,
            COALESCE(v.vitorias, 0) AS vitorias
        FROM group_members gm
        JOIN entries e ON e.id = gm.entry_id
        JOIN players p ON p.id = e.player_id
        LEFT JOIN vitorias v ON v.player_id = p.id
        WHERE gm.group_id = (SELECT id FROM div3)
        ORDER BY vitorias DESC, p.name;
        ```

        Second example (global ranking, NOT division standings):

        Input question:
        "Quem está no top 3 do ranking geral?"

        Output:
        ```sql
        SELECT p.name, p.ranking_points, p.ranking_position
        FROM players p
        WHERE p.ranking_position > 0
        ORDER BY p.ranking_points DESC, p.ranking_position ASC
        LIMIT 3;
        ```

        Third example (final standings of a finished division):

        Input question:
        "Qual foi a classificação final da 1ª divisão da última edição?"

        Output:
        ```sql
        WITH div1 AS (
            SELECT g.id
            FROM competition_groups g
            JOIN stages st ON st.id = g.stage_id
            JOIN competitions c ON c.id = st.competition_id
            WHERE c.format = 'classica' AND g.rating = 2000 AND g.has_ended = TRUE
            ORDER BY c.starts_on DESC NULLS LAST, g.id DESC
            LIMIT 1
        )
        SELECT ss.place, p.name, ss.points, ss.wins, ss.draws, ss.losses, ss.games_won, ss.games_lost
        FROM standing_snapshots ss
        JOIN group_members gm ON gm.id = ss.group_member_id
        JOIN entries e ON e.id = gm.entry_id
        JOIN players p ON p.id = e.player_id
        WHERE gm.group_id = (SELECT id FROM div1)
        ORDER BY ss.place;
        ```

        Write a valid PostgreSQL query that answers the following question.
        Return **only** a fenced markdown code block. No extra explanation.

        Question: {user_question}
        Answer:
        """

    def run(self, question, max_retries=1):
        llm_answer = self.ask_llm_client(self.prompt(question))
        sql = self.extract_sql_block(llm_answer)
        try:
            rows = self.sql_client.execute(sql)
            return {"sql": sql, "rows": rows}

        except DatabaseError as e:
            if max_retries <= 0:
                raise

            repaired_sql = self.repair_sql(question, sql, str(e))
            try:
                rows = self.sql_client.execute(repaired_sql)
                return {
                    "sql": repaired_sql,
                    "rows": rows,
                    "repaired_from": sql,
                    "error": str(e),
                }
            except DatabaseError:
                return {
                    "sql": repaired_sql,
                    "rows": "There was an error retrieving the data",
                    "repaired_from": sql,
                    "error": str(e),
                }


class GenericAnswerAgent(Agent):

    name = "GenericAnswerAgent"
    description = """
    General conversational assistant. Handles questions unrelated to padel or the league.
    Takes a full natural-language question and returns a general answer.
    """

    system_prompt = """
    És um assistente útil.
    Responde sempre em Português de Portugal.
    Usa vocabulário e ortografia europeia.
    Se o utilizador escrever noutra língua, responde em PT-PT.
    NUNCA respondas em PT-BR.
    """

    def __init__(self, api_key):
        self.llm = LLMClient(api_key=api_key)

    def run(
        self, original_question, agent_question, conversation=None, trace=None
    ) -> str:

        if conversation:
            conversation = copy.deepcopy(conversation)

        prompt = f"""
        You are a helpful and friendly AI Agent. An Orchestrator has interpreted a conversation and provided a question for you.
        You'll be sent the user question, and the orchestrator interpretation. Answer naturally.

        Answer the user's question naturally.

        User question:
        {original_question}

        The orchestrator agent interpreted this as:

        {agent_question}

        Always answer in European Portuguese. Portuguese from Portugal. Never speak Brazilian.
        """

        if conversation:
            conversation.update_system_prompt(self.system_prompt)
            conversation.add_message(role="user", content=prompt)
            answer = self.llm.generate_response_for_conversation(
                conversation=conversation, reasoning_effort="minimal", verbosity="low"
            )
        else:
            answer = self.llm.generate_response(
                prompt=prompt,
                reasoning_effort="minimal",
                verbosity="low",
                initial_instruction=self.system_prompt,
            )

        return answer

    def run_debug(self, original_question, agent_question: str) -> str:
        prompt = f"""
        You are a helpful and friendly assistant.

        Answer the user's question naturally.

        User question:
        {original_question}

        The orchestrator agent interpreted this as:

        {agent_question}
        """

        answer = self.llm.generate_response(
            prompt=prompt, reasoning_effort="minimal", verbosity="low"
        )
        return {"agent_question": agent_question, "answer": answer}


class PadelLeagueAnswerAgent(Agent):

    name = "PadelLeagueAnswerAgent"
    description = """
    Padel League conversational assistant. Handles questions related to the padel league.
    Takes a full natural-language question, calls the SQL agent to generate a SQL query to fetch information from the DB.

    Has access to a SQL agent that retrieves structured data from the SQL database.
    Takes a list of fully-formed natural-language questions about the padel league,
    divisions, matches, schedules, rankings, or players.
    """

    system_prompt = """
    És um assistente da Porto Padel League.
    És um especialista em informação sobre esta liga amigável.
    Responde sempre em Português de Portugal.
    Usa vocabulário e ortografia europeia.
    Se o utilizador escrever noutra língua, responde em PT-PT.
    NUNCA respondas em PT-BR.
    """

    def __init__(self, api_key, data_agent):
        self.llm = LLMClient(api_key=api_key)
        self.data_agent = data_agent

    def run(
        self, original_question, agent_questions, conversation=None, trace=None
    ) -> str:

        if conversation:
            conversation = copy.deepcopy(conversation)

        db_result = [
            {"question": question, "db_result": self.data_agent.run(question)}
            for question in agent_questions
        ]
        if trace is not None:
            trace["sql_queries"] = [
                {
                    "question": item["question"],
                    "sql": item["db_result"].get("sql"),
                    "repaired_from": item["db_result"].get("repaired_from"),
                    "error": item["db_result"].get("error"),
                    "row_count": (
                        len(item["db_result"]["rows"])
                        if isinstance(item["db_result"].get("rows"), list)
                        else None
                    ),
                }
                for item in db_result
            ]

        db_rows_str = "\n".join(
            f"Question: {item['question']}\nRows: {item['db_result'].get('rows', [])}\n"
            for item in db_result
        )

        prompt = f"""
        You are the Padel League Assistant.

        The user asked you this:

        {original_question}

        The orchestrator agent interpreted this and made the following questions to the data agent, who already answered.
        Here is data retrieved from the database:

        {db_rows_str}

        Craft a precise, correct, sarcastic answer based on the data.
        Always answer in European Portuguese. You should be funny and sarcastic.

        If the information is missing please tell the user that you coulnd't retrieve information from the db,
        ask him to rephrase the question. Only do this if the information is missing.

        Don't talk about the table you received, the rows etc, etc. This is internal work that the user is not privy to. He just asked the original question.
        Always answer in European Portuguese. Portuguese from Portugal. Never speak Brazilian.
        """

        if conversation:
            conversation.update_system_prompt(self.system_prompt)
            conversation.add_message(role="user", content=prompt)
            answer = self.llm.generate_response_for_conversation(
                conversation=conversation, reasoning_effort="minimal", verbosity="low"
            )
        else:
            answer = self.llm.generate_response(
                prompt=prompt,
                reasoning_effort="minimal",
                verbosity="low",
                initial_instruction=self.system_prompt,
            )

        return answer

    def run_debug(self, original_question, agent_questions: str) -> str:
        db_result = [
            {"question": question, "db_result": self.data_agent.run(question)}
            for question in agent_questions
        ]

        db_rows_str = "\n".join(
            f"Question: {item['question']}\nRows: {item['db_result'].get('rows', [])}\n"
            for item in db_result
        )

        prompt = f"""
        You are the Padel League Assistant.

        The user asked you this:

        {original_question}

        The orchestrator agent interpreted this and made the following questions to the data agent, who already answered.
        Here is data retrieved from the database:

        {db_rows_str}

        Craft a precise, correct, sarcastic answer based on the data.
        Always answer in European Portuguese. You should be funny and sarcastic.

        If the information is missing please tell the user that you coulnd't retrieve information from the db,
        ask him to rephrase the question. Only do this if the information is missing.

        Don't talk about the table you received, the rows etc, etc. This is internal work that the user is not privy to. He just asked the original question.
        """

        answer = self.llm.generate_response(
            prompt=prompt, reasoning_effort="minimal", verbosity="low"
        )

        return {
            "db_result": db_result,
            "answer": answer,
        }


class OrchestratorAgent:

    system_prompt = """
    You're an orchestrator agent, charged with processing a conversation and giving tasks to other AI Agents.
    Always ask your questions in English.

    Your job is to:
    1. Understand the user's message IN CONTEXT of the conversation.
    2. Rewrite the message into one or more explicit questions.
    3. Decide which agent should answer each question.
    4. Output ONLY valid JSON.

    Here are the available agents:
    {self.agents_description}

    Rules:
    - If the question is NOT related to padel or the padel league → assign to GenericAnswerAgent.
    - If the question IS related to padel league, divisions, players, standings, matches → assign to PadelLeagueAnswerAgent.
    - If the user asks multiple questions, split them into separate tasks, each understandable for a standalone agent.
    - If the user refers to previous context (e.g. "and division 2?"), rewrite into a full, explicit question.
    - Keep the questions as simple as possible. Don't add information you don't see somewhere in the conversation.
    - ALWAYS return a JSON object with a top-level field "agent", which is a list of calls.

    Example output format:
    {{
    "agent": [
        {{
        "name": "PadelLeagueAnswerAgent",
        "question": [
            "What are the points for division 2 in the 2024 season?",
            "How many victories has the first place of division 2 in the 2024 season?"
            ]
        }}
    ]
    }}

    or

    {{
    "agent": [
        {{
        "name": "GenericAnswerAgent",
        "question": [
            "Explain why padel is so popular."
            ]
        }}
    ]
    }}

    """

    def __init__(self, api_key, agents):
        self.llm = LLMClient(api_key=api_key, model="gpt-5.1")
        self.agents = agents
        self.agents_description = [
            {"name": agent.name, "description": agent.description} for agent in agents
        ]
        # The class-level prompt is a template; render the agent list into it.
        self.system_prompt = self.__class__.system_prompt.format(self=self)
        self.conversation = self.new_conversation()
        self.agents_dict = {agent.name: agent for agent in agents}

    def new_conversation(self):
        """A fresh, independent conversation (one per chat session)."""
        return LLMConversation(system_prompt=self.system_prompt)

    @staticmethod
    def parse_tasks(raw):
        """
        Parses the orchestrator's JSON answer, tolerating ```json fences and
        stray text around the object.
        """
        if not raw:
            raise ValueError("Orchestrator returned an empty answer")
        text = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end == -1:
                raise
            return json.loads(text[start : end + 1])

    def choose_agents(self, user_message, conversation=None):
        prompt = f"""
        This was the last user message.

        User message:
        {user_message}

        Send the tasks to the specific agents.
        Respond with JSON only.
        """

        base = conversation if conversation is not None else self.conversation
        new_conversation = copy.deepcopy(base)
        new_conversation.add_message("user", prompt)

        raw = self.llm.generate_response_for_conversation(
            conversation=new_conversation,
            reasoning_effort="none",
            verbosity="low",
            temperature=0,
        )
        return self.parse_tasks(raw)

    def run(self, user_message, conversation=None, trace=None):
        """
        Answers `user_message` in the context of `conversation` (defaults to
        the orchestrator's own conversation) and records the exchange in it.

        If `trace` is a dict it is filled with the routing decision and the
        SQL that ran, so the caller can log it.
        """
        conversation = conversation if conversation is not None else self.conversation
        tasks = self.choose_agents(user_message, conversation)
        calls = tasks.get("agent") or []
        if not calls:
            raise ValueError(f"Orchestrator returned no agent call: {tasks!r}")
        agent_name = calls[0]["name"]
        agent_question = calls[0]["question"]
        agent = self.agents_dict.get(agent_name)
        if agent is None:
            agent = self.agents_dict["GenericAnswerAgent"]
        if trace is not None:
            trace["agent_name"] = agent.name
            trace["agent_questions"] = agent_question
        answer = agent.run(user_message, agent_question, conversation, trace=trace)
        if answer:
            conversation.add_message("user", user_message)
            conversation.add_message("assistant", answer)
        return answer
