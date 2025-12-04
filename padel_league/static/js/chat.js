const chatContainer = document.getElementById('chatContainer');
const userInputDiv = document.getElementById('user_input');
const sendButton = document.getElementById('sendButton');
const chatbotInitialGreeting = document.getElementById('chatbot_initial_greeting');

let messages = []; // Stores all messages

/**
 * Escapes HTML to prevent XSS attacks.
 * @param {string} str - The user input to escape.
 * @returns {string} - The escaped string.
 */
function escapeHTML(str) {
    return str.replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


/**
 * Creates a message element and appends it to the chat container.
 * @param {'user' | 'bot'} sender - The sender of the message.
 * @returns {HTMLElement} The created message element.
 */
function createMessageElement(sender) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', sender === 'user' ? 'user-message' : 'bot-message');
    chatContainer.appendChild(messageDiv);
  
    if (messages.length === 1) {
      chatContainer.classList.remove('hiddenDiv');
    }
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return messageDiv;
}

/**
 * Appends a message to the chat container.
 * @param {string} message - The message text.
 * @param {'user' | 'bot'} sender - The sender of the message.
 * @param {boolean} [animate=false] - If true, the text is revealed as a typing effect.
 */
function addMessageToChat(message, sender, animate = false) {
    if (!message) return;
  
    messages.push({ sender, message });
    const messageDiv = createMessageElement(sender);
  
    if (!animate) {
      messageDiv.innerHTML = escapeHTML(message).replace(/\n/g, '<br>');
    } else {
      let index = 0;
      const typingDelay = 10;
  
      function typeNextChar() {
        if (index < message.length) {
          messageDiv.innerHTML += escapeHTML(message.charAt(index));
          index++;
          chatContainer.scrollTop = chatContainer.scrollHeight;
          setTimeout(typeNextChar, typingDelay);
        }
      }
      typeNextChar();
    }
}

/**
 * Adds a loading animation in the chat container.
 * Returns the loading element so it can be removed later.
 */
function addLoadingMessage() {
    const loadingDiv = document.createElement('div');
    loadingDiv.classList.add('message');
    loadingDiv.id = 'loadingMessage';
    loadingDiv.innerHTML = '<span class="chatbot_loader"></span>';
    chatContainer.appendChild(loadingDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return loadingDiv;
}

/**
 * Sends the user's message to the server.
 */
async function sendMessage() {
    chatbotInitialGreeting.remove()
    const userInput = userInputDiv.innerText.trim();
    if (!userInput) return;

    addMessageToChat(userInput, 'user');
    userInputDiv.innerHTML = '';

    const loadingElement = addLoadingMessage();

    try {
        const response = await fetch('chatbot_api/chat', {
            method: 'POST',
            body: new URLSearchParams({ user_input: userInput }),
        });

        if (!response.ok) throw new Error(`Server responded with ${response.status}`);

        const data = await response.json();

        if (loadingElement && loadingElement.parentNode) {
            loadingElement.parentNode.removeChild(loadingElement);
        }

        if (data.response) {
            addMessageToChat(data.response, 'bot', true);
        } else {
            addMessageToChat('No response from server', 'bot');
        }
    } catch (error) {
        if (loadingElement && loadingElement.parentNode) {
            loadingElement.parentNode.removeChild(loadingElement);
        }
        addMessageToChat(`Error: ${error.message}`, 'bot');
    }
}

/**
 * Handles keyboard events in the input field.
 */
userInputDiv.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

/**
 * Handles click events for the send button.
 */
sendButton.addEventListener('click', (e) => {
    e.preventDefault();
    sendMessage();
});
