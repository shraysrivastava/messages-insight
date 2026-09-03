# The image is the game and nothing else.
#
# What ships:  app/  static/  datasets/  and two files out of tools/.
# What doesn't: corpus.json, candidates.json, questions/, the rest of tools/,
# the tests, the POC. The only real data in here is ciphertext, and the key
# to it is in one person's head (docs/PLAN.md §4).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Runtime dependencies only — no pytest, no authoring tools. Copied on its own
# so a question edit doesn't invalidate the layer and re-resolve every wheel.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/
COPY datasets/ datasets/

# app/datasets.py opens the sealed dataset through tools/seal.py. That one
# module, and nothing else from tools/ — `mine.py` and friends have no business
# on a public host.
COPY tools/__init__.py tools/seal.py tools/

EXPOSE 8000

# A machine that answers /healthz is a machine Fly won't recycle under a lobby
# that's been sitting idle while two people find the remote.
HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"

CMD ["python", "-m", "app.main", "--data", "datasets/demo.json", "--host", "0.0.0.0"]
