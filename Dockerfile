FROM python:3.13-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && rm -rf /usr/local/lib/python3*/site-packages/pip \
           /usr/local/lib/python3*/site-packages/pip-*.dist-info \
           /usr/local/lib/python3*/site-packages/setuptools \
           /usr/local/lib/python3*/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3*/site-packages/pkg_resources \
           /usr/local/lib/python3*/site-packages/wheel \
           /usr/local/lib/python3*/site-packages/wheel-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /usr/local/lib/python3*/ensurepip

COPY *.py .

ENTRYPOINT ["python", "main.py"]
CMD ["monitor"]
