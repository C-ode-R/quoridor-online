FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY sdk/python ./sdk/python
RUN python -m pip install --upgrade pip \
    && python -m pip install ./sdk/python \
    && python -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.2" \
    && python -m pip install "numpy>=1.26"

COPY rl ./rl
RUN python -m pip install --no-deps ./rl \
    && chmod +x /workspace/rl/run_training.sh

ENTRYPOINT ["/workspace/rl/run_training.sh"]
