import re
from pandas.errors import DatabaseError
import json
import copy
from .llm_handler import LLMConversation


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

    def __init__(self, llm_client, sql_client):
        self.llm_client = llm_client
        self.sql_client = sql_client

        self.schema = """
        ## Table leagues
        leagues (
        id BIGINT PRIMARY KEY,
        name TEXT
        )

        ## Table editions
        editions (
        id BIGINT PRIMARY KEY,
        name TEXT,
        league_id BIGINT REFERENCES leagues(id)
        )

        ## Table divisions
        divisions (
        id BIGINT PRIMARY KEY,
        name TEXT,
        beginning_datetime TIMESTAMP,
        rating BIGINT,
        end_date TIMESTAMP,
        logo_image_path TEXT,
        large_picture_path TEXT,
        has_ended BOOLEAN,
        open_division BOOLEAN,
        edition_id BIGINT REFERENCES editions(id),
        logo_image_id INTEGER,
        large_picture_id INTEGER
        )

        ## Table players
        players (
        id BIGINT PRIMARY KEY,
        name TEXT,
        full_name TEXT,
        birthday TIMESTAMP,
        picture_path TEXT,
        large_picture_path TEXT,
        ranking_points BIGINT,
        ranking_position BIGINT,
        height DOUBLE PRECISION,
        prefered_hand TEXT,
        prefered_position TEXT
        )

        ## Table players_in_division
        players_in_division (
        id BIGINT PRIMARY KEY,
        player_id BIGINT REFERENCES players(id),
        division_id BIGINT REFERENCES divisions(id),
        place BIGINT,
        points DOUBLE PRECISION,
        appearances BIGINT,
        percentage_of_appearances DOUBLE PRECISION,
        wins BIGINT,
        draws BIGINT,
        losts BIGINT,
        games_won BIGINT,
        games_lost BIGINT,
        matchweek BIGINT
        )

        ## Table matches
        matches (
        id BIGINT PRIMARY KEY,
        games_home_team BIGINT,
        games_away_team BIGINT,
        date_hour TIMESTAMP,
        winner BIGINT,
        matchweek BIGINT,
        field TEXT,
        played BOOLEAN,
        division_id BIGINT REFERENCES divisions(id)
        )

        ## Table players_in_match
        players_in_match (
        id BIGINT PRIMARY KEY,
        player_id BIGINT REFERENCES players(id),
        match_id BIGINT REFERENCES matches(id),
        team TEXT
        )
        """

    def ask_llm_client(self, prompt):
        return self.llm_client.generate_response(
            prompt=prompt, reasoning_effort="none", temperature=0, verbosity="low"
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
            model="gpt-5.1",
            prompt=repair_prompt,
            reasoning_effort="medium",
            verbosity="low",
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

        1. Divisions are current when has_ended = FALSE.
        2. Current edition = edition where all its divisions have has_ended = FALSE.
        3. Closed edition = all divisions have has_ended = TRUE.
        4. When ask about a “Division”, default is the division with that rating in the current edition.
        5. “Última edição” usually means last closed edition.
        6. Divisions identified by rating, not name:
        2000 → D1, 1000 → D2, 500 → D3, 250 → D4, 125 → D5.
        7. For place/points/faltas questions → current edition.
        8. For historical counts → all editions.
        9. matches.winner stores **1 for home team win**, **-1 for away team win**, **0 for tie** — NOT a player_id.
        10. To get the winning **players**, match the team logic:
            - If winner = 1 → winners are players where LOWER(team) = 'home'
            - If winner = -1 → winners are players where LOWER(team) = 'away'
        11. Do NOT compare TEXT with BIGINT.
        12. players_in_match shows who played each match.
        13. team is literal text 'home' or 'away'.
        14. Improvements only between **closed editions**.
        15. melhoria = place_prev - place_curr.
        16. Include edition names and division ratings when comparing improvements.
        17. 'Parelha' are the 2 players that play together in one matchweek. 'Parelha de X' is the player that played with X in a certain matchweek.
        18. Being promoted means being in the top 2 places of a division in the end (matchweek 7), being relegated means being in the bottom 2 places in that matchweek.
        19. To understand how many points a player would need to be champion, compare that points from the 1st place and the points from that player.
        20. If a question implies a comparison try to write a query that would return enough information for the final agent to craft a complete answer to the question.
        21. If a question is about points regarding games, they can be calculated easily, 3 points for victory, 1 point for a draw.
        22. Always use explicit joins via IDs.
        23. Use correct PostgreSQL types consistently.
        24. Avoid invalid or non-existent column names.
        25. Follow strict PostgreSQL GROUP BY rules.


        ---

        # Interpreting ambiguous questions
        - “Divisão X” → current edition’s division.
        - “Última edição” → last closed edition.
        - Historical questions → all editions.
        - “Quantas vezes jogou a 1ª divisão?” → count all divisions rating = 2000.
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
            SELECT id
            FROM divisions
            WHERE rating = 500
            AND has_ended = FALSE
            ORDER BY id DESC
            LIMIT 1
        ),
        vitorias AS (
            SELECT
                pim.player_id,
                COUNT(*) AS vitorias
            FROM matches m
            JOIN players_in_match pim ON pim.match_id = m.id
            WHERE m.division_id = (SELECT id FROM div3)
            AND m.played = TRUE
            AND (
                    (m.winner = 1  AND LOWER(pim.team) = 'home')
                OR  (m.winner = -1 AND LOWER(pim.team) = 'away')
            )
            GROUP BY pim.player_id
        )
        SELECT
            p.name,
            COALESCE(v.vitorias, 0) AS vitorias
        FROM players_in_division pid
        JOIN players p ON p.id = pid.player_id
        LEFT JOIN vitorias v ON v.player_id = p.id
        WHERE pid.division_id = (SELECT id FROM div3)
        ORDER BY vitorias DESC, p.name;
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

    def __init__(self, llm):
        self.llm = llm

    def run(self, original_question, agent_question: str) -> str:
        prompt = f"""
        You are a helpful and friendly assistant.

        Answer the user's question naturally.

        User question:
        {original_question}

        The orchestrator agent interpreted this as:

        {agent_question}
        """
        return self.llm.generate_response(
            prompt=prompt, reasoning_effort="minimal", verbosity="low"
        )

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

    def __init__(self, llm, data_agent):
        self.llm = llm
        self.data_agent = data_agent

    def run(self, original_question, agent_questions: str) -> str:
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

        return self.llm.generate_response(
            prompt=prompt, reasoning_effort="minimal", verbosity="low"
        )

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
    def __init__(self, llm, agents):
        self.llm = llm
        self.agents = agents
        self.agents_description = [
            {"name": agent.name, "description": agent.description} for agent in agents
        ]
        self.conversation = LLMConversation()
        self.agents_dict = {agent.name: agent for agent in agents}

    def choose_agents(self, user_message):
        prompt = f"""
        You are the Orchestrator Agent in a multi-agent system.

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

        User message:
        {user_message}

        Respond with JSON only.
        """

        new_conversation = copy.deepcopy(self.conversation)
        new_conversation.add_message("user", prompt)

        raw = self.llm.generate_response_for_conversation(
            conversation=new_conversation,
            reasoning_effort="none",
            verbosity="low",
            temperature=0,
        )
        return json.loads(raw)

    def run(self, user_message):
        tasks = self.choose_agents(user_message)
        agent_name = tasks["agent"][0]["name"]
        agent_question = tasks["agent"][0]["question"]
        agent = self.agents_dict[agent_name]
        answer = agent.run(user_message, agent_question)
        self.conversation.add_message("user", user_message)
        self.conversation.add_message("assistant", answer)
        return answer
