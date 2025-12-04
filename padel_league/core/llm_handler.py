import concurrent.futures
import logging
from openai import OpenAI
from openai._types import NOT_GIVEN
from typing import List, Optional, Dict
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    """
    Represents a single message in a conversation, with naive token counting
    and a validate() method to check tokens and role.
    """

    role: str
    content: str
    max_tokens: int = 2048

    def estimate_tokens(self) -> int:
        """
        Estimates the number of tokens of the content based on a naive word-count approach.
        We use the rule of thumb that 100 tokens are roughly 75 words,
        hence 1 token ≈ 0.75 words.

        Args:
            text (str): The text to estimate the token usage for.

        Returns:
            int: The approximate token count for the provided text.
        """
        word_count = len(self.content.split())
        approx_tokens = word_count / 0.75
        return int(round(approx_tokens))

    def validate(self) -> bool:
        """
        Checks whether the role is valid and whether the token count stays
        below the configured max_tokens. Logs a warning if either fails.

        Valid roles currently include: "system", "user", and "assistant".

        Returns:
            bool: True if the message is considered valid, False otherwise.
        """
        valid_roles = {"system", "user", "assistant"}

        if self.role not in valid_roles:
            logging.warning(
                f"Invalid role '{self.role}'. Must be one of {valid_roles}."
            )
            return False

        if self.estimate_tokens() > self.max_tokens:
            logging.warning(
                f"Message token count ({self.estimate_tokens()}) exceeds the limit ({self.max_tokens})."
            )
            return False

        return True

    def to_openai_format(self) -> Dict[str, str]:
        """
        Returns a dictionary with the appropriate format for an OpenAI object.

        Returns:
            Dict[str, str]: A dictionariy in the format:

            {"role": "user" or "assistant", "content": "..."}
        """
        return {"role": self.role, "content": self.content}


@dataclass
class LLMConversation:
    """
    Represents a conversation consisting of a single system message at initialization,
    followed by multiple LLMMessage objects, with a maximum approximate token limit.
    """

    system_prompt: str = "You are a helpful assistant."
    max_total_tokens: int = 2048
    messages: List[LLMMessage] = field(init=False, default_factory=list)

    def __post_init__(self):
        """
        Automatically create and store the system message as the first message in the conversation.
        """
        self.add_message(role="system", content=self.system_prompt)

    def add_message(self, role: str, content: str, max_tokens: int = 2048):
        """
        Adds a new message to the conversation.

        Args:
            role (str): The role of the message (e.g., 'user', 'assistant').
            content (str): The textual content of the message.
            max_tokens (int, optional): The maximum number of tokens allowed for this message.
                Defaults to 2000.
        """
        msg = LLMMessage(role=role, content=content, max_tokens=max_tokens)
        if msg.validate():
            self.messages.append(msg)
            return True
        return False

    def to_openai_format(self) -> List[Dict[str, str]]:
        """
        Returns a list of messages (role/content) suitable for OpenAI's ChatCompletion,
        ensuring the total approximate token usage does not exceed max_total_tokens.

        If the total exceeds max_total_tokens, it removes older messages from the conversation
        (excluding the first system message) until the approximate token count fits within the limit.

        Returns:
            List[Dict[str, str]]: A list of dictionaries in the format:
            [
                {"role": "system", "content": "<system_prompt>"},
                {"role": "user" or "assistant", "content": "..."},
                ...
            ]
        """
        conversation_list = self.messages.copy()

        total_tokens = self.compute_total_tokens()
        idx = 1
        while total_tokens > self.max_total_tokens and idx < len(conversation_list):
            removed_message = conversation_list.pop(idx)
            removed_tokens = removed_message.estimate_tokens()
            total_tokens -= removed_tokens

        conversation_list = [m.to_openai_format() for m in self.messages]
        return conversation_list

    def compute_total_tokens(self) -> int:
        """
        Computes an approximate token count for the entire conversation.

        Returns:
            int: The approximate total token count for the conversation.
        """
        return sum([m.estimate_tokens() for m in self.messages])


class LLMClient:
    """A class to interact with an OpenAI inference model using the Responses API."""

    def __init__(
        self, base_url: str = None, model: str = "gpt-5-nano", api_key: str = "EMPTY"
    ) -> None:
        if base_url:
            self.client = OpenAI(base_url=base_url, api_key=api_key)
        else:
            self.client = OpenAI(api_key=api_key)
        self.model = model

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()],
        )

    def generate_response_for_conversation(
        self,
        conversation: LLMConversation,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        verbosity: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Generates a response using the Responses API, keeping the existing
        LLMConversation and LLMMessage structure intact.
        """

        reasoning = (
            {"effort": reasoning_effort} if reasoning_effort is not None else NOT_GIVEN
        )
        text = {"verbosity": verbosity} if verbosity is not None else NOT_GIVEN

        try:
            response = self.client.responses.create(
                model=self.model if not model else model,
                input=conversation.to_openai_format(),
                temperature=temperature if temperature is not None else NOT_GIVEN,
                top_p=top_p if top_p is not None else NOT_GIVEN,
                max_output_tokens=max_tokens if max_tokens is not None else NOT_GIVEN,
                reasoning=reasoning,
                text=text,
            )
            return response.output_text

        except Exception as e:
            logging.error("Failed to get response from model: %s", e)
            return None

    def generate_response(
        self,
        prompt: str,
        model: Optional[str] = None,
        initial_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        verbosity: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Generates a response to a single prompt, using LLMConversation internally.
        """

        initial_instruction = initial_instruction or "You are a helpful assistant."

        conversation = LLMConversation(system_prompt=initial_instruction)
        conversation.add_message(role="user", content=prompt)

        return self.generate_response_for_conversation(
            model=self.model if not model else model,
            conversation=conversation,
            temperature=temperature,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            max_tokens=max_tokens,
            **kwargs,
        )

    def generate_multiple_responses(
        self,
        list_of_prompts: List[str],
        reasoning_effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> List[Optional[str]]:
        """
        Generates multiple responses in parallel using the same wrapper.
        """

        responses = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(
                    self.generate_response,
                    prompt,
                    None,
                    temperature,
                    top_p,
                    reasoning_effort,
                    max_tokens,
                )
                for prompt in list_of_prompts
            ]

            for future in concurrent.futures.as_completed(futures):
                responses.append(future.result())

        return responses
