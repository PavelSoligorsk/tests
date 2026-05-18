import os
from mistralai.client import Mistral
from dotenv import load_dotenv

import os
load_dotenv()

SECRET_KEY = os.getenv("MISTRAL_TOKEN")

# Initialize the client with your API key
client = Mistral(api_key=SECRET_KEY)

# Send a request to the chat completion endpoint
response = client.chat.complete(
    model="mistral-large-latest",
    messages=[
        {"role": "user", "content": "https://i.postimg.cc/8cD2X9Qp/изображение.png"}
    ],
)

# Print the model's response
print(response.choices[0].message.content)
