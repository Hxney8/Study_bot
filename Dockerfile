FROM python:3.10-slim
WORKDIR /
RUN apt update && apt install -y libreoffice libreoffice-writer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm -rf /root/.cache
COPY . .
EXPOSE 8080
CMD ["python", "bot.py"]