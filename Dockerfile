FROM python:3.13-alpine

# patch base-image CVEs (alpine ships fixes faster than the python image is rebuilt)
RUN apk upgrade --no-cache

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY mev_bot_watcher ./mev_bot_watcher
RUN pip install --no-cache-dir . \
 && rm -rf /usr/local/lib/python3*/site-packages/pip \
           /usr/local/lib/python3*/site-packages/pip-*.dist-info \
           /usr/local/lib/python3*/site-packages/setuptools \
           /usr/local/lib/python3*/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3*/site-packages/pkg_resources \
           /usr/local/lib/python3*/site-packages/wheel \
           /usr/local/lib/python3*/site-packages/wheel-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /usr/local/lib/python3*/ensurepip

ENTRYPOINT ["mev-watcher"]
CMD ["monitor"]
