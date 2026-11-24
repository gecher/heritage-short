# Windows without make: run the same commands with python -m pipeline <command>
PY ?= python
install: ; $(PY) -m pip install -r requirements.txt
validate: ; $(PY) -m pipeline validate
smoke: ; $(PY) -m pipeline smoke
film: ; $(PY) -m pipeline film
.PHONY: install validate smoke film
