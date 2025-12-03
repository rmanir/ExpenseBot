import os
from dotenv import load_dotenv
load_dotenv()
print("BOT_TOKEN:", os.getenv("BOT_TOKEN"))