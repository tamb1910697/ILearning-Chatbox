FROM python:3.7-stretch AS BASE

RUN apt-get update && \
    apt-get --assume-yes --no-install-recommends install \
    build-essential \
    curl \
    git \
    jq \
    libgomp1 \
    vim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

# To install packages from PyPI
COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy actions folder to working directory
COPY ./actions /app/actions

ADD config.yml config.yml
ADD domain.yml domain.yml
ADD credentials.yml credentials.yml
ADD endpoints.yml endpoints.yml

EXPOSE 5005
CMD ["--help"]
