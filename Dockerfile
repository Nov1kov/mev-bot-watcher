FROM python:3.13-alpine

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
