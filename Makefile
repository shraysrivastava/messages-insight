# Read Receipts. Run `make` to see what's done and what's left.
PY := ./.venv/bin/python

.DEFAULT_GOAL := status
.PHONY: status setup test lint demo play extract corpus mine curate compile seal unseal poc clean

status:            ## what's done, what's left
	@$(PY) tools/status.py

setup:             ## create .venv and install everything
	/opt/homebrew/bin/python3.14 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt
	@echo "ready — run 'make demo'"

test:              ## run the test suite
	@$(PY) -m pytest -q

lint:              ## check questions/ and the compiled datasets
	@$(PY) tools/validate.py datasets/demo.json

demo: demo_corpus.json  ## build the safe fake dataset end to end
	@$(PY) tools/compile.py --corpus demo_corpus.json --out datasets/demo.json

demo_corpus.json:
	@$(PY) tools/make_demo_corpus.py --out demo_corpus.json

play: demo         ## play the demo (fake) dataset
	$(PY) -m app.main --data datasets/demo.json

serve:             ## serve any dataset:  make serve DATA=datasets/test.json
	$(PY) -m app.main --data $(DATA) --rounds $(ROUNDS) --seconds $(SECONDS)

poc:               ## the original proof of concept, kept runnable as a fallback
	$(PY) poc/server.py --data datasets/demo.json

# ── the real thing. Needs Full Disk Access for your terminal. ──────────────

chats:             ## list your iMessage threads, to find the identifier
	@$(PY) tools/extract.py --list

CORPUS  ?= corpus.json
DATASET ?= datasets/real.json
# Extraction-time names barely matter — compile.py overrides them from
# questions/config.toml. These just keep the command short.
P1 ?= Me
P2 ?= Her
DATA    ?= datasets/test.json
ROUNDS  ?= 10
SECONDS ?= 25
PORT    ?= 8900

corpus:            ## chat.db -> $(CORPUS)   (CHAT=... P1=... P2=...)
	@test -n "$(CHAT)" || (echo "usage: make corpus CHAT='+1555…' P1=Me P2=Them"; exit 1)
	@$(PY) tools/extract.py --chat "$(CHAT)" --p1 "$(P1)" --p2 "$(P2)" --out $(CORPUS)
	@echo "  next:  make compile && make real"

mine:              ## $(CORPUS) -> candidates.json
	@$(PY) tools/mine.py --corpus $(CORPUS) --out candidates.json

curate: candidates.json  ## review candidates in the browser -> questions/mine.toml
	@$(PY) tools/curate.py --corpus $(CORPUS) --port $(PORT)

candidates.json:
	@$(MAKE) mine

compile:           ## questions/ + $(CORPUS) -> $(DATASET)
	@$(PY) tools/compile.py --corpus $(CORPUS) --out $(DATASET)

seal:              ## encrypt $(DATASET) + questions/mine.toml -> .enc (committed)
	@$(PY) tools/seal.py --all

unseal:            ## restore questions/mine.toml from its .enc
	@$(PY) tools/seal.py --open questions/mine.toml.enc --out questions/mine.toml

real: compile      ## play the real dataset locally
	$(PY) -m app.main --data $(DATASET)

# A whole thread end to end, into throwaway files. For testing on someone
# who isn't her:  make try CHAT="+1555..." P1=Me P2=Dave
try:
	@$(MAKE) corpus CORPUS=test_corpus.json CHAT="$(CHAT)" P1="$(P1)" P2="$(P2)"
	@$(MAKE) compile CORPUS=test_corpus.json DATASET=datasets/test.json
	@$(PY) poc/server.py --data datasets/test.json

clean:
	rm -f demo_corpus.json candidates.json
	rm -rf .pytest_cache **/__pycache__

help:
	@grep -E '^[a-z_]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'
