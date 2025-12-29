# Use a lightweight Python version
FROM python:3.10-slim

# 1. Install FFmpeg and system dependencies
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean

# 2. Set the working directory
WORKDIR /app

# 3. Copy your project files into the container
COPY . .

# 4. Install Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# 5. Run the bot
CMD ["python", "bot.py"]
