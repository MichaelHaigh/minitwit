FROM python:3.10.12

ENV FLASK_APP=minitwit

RUN apt-get clean \
    && apt-get -y update

COPY . /app

WORKDIR /app

RUN pip install -r requirements.txt --src /usr/local/src

EXPOSE 5000

CMD [ "flask", "run", "--host=0.0.0.0" ]
