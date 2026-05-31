FROM ubuntu:22.04
COPY ./judge-py /judge-py
WORKDIR /root

RUN apt-get update
RUN apt -y install python3
RUN apt -y install python3-pip
RUN pip install -r /judge-py/requirements.txt
